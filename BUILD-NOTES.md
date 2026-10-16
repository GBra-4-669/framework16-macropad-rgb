# Build and flash notes

Session log for the work that produced `firmware-panel-palette.uf2`, including what
went wrong. `README.md` has the short version.

## Toolchain

Everything comes from the distro except the QMK CLI, which is not packaged
(installed on Fedora 43 here; the CLI is missing because Fedora's Python is
externally managed):

    arm-none-eabi-gcc-cs arm-none-eabi-gcc-cs-c++ arm-none-eabi-binutils-cs arm-none-eabi-newlib

The QMK CLI lives in its own venv, which also holds the build tree's
`requirements.txt`:

    python3 -m venv ~/.local/share/qmk-venv
    ~/.local/share/qmk-venv/bin/pip install qmk -r requirements.txt

## Build tree

`FrameworkComputer/qmk_firmware`, branch `fl16-2025`, shallow-cloned with shallow
submodules. The macropad's keyboard definitions are on that branch and not in
upstream QMK master.

    git clone --branch fl16-2025 --depth 1 \
        https://github.com/FrameworkComputer/qmk_firmware.git ~/qmk-framework
    cd ~/qmk-framework
    git submodule update --init --depth 1

## Build

    cd ~/qmk-framework
    QMK_HOME=$PWD ~/.local/share/qmk-venv/bin/qmk compile -kb framework/macropad -km palette

Output: `framework_macropad_default.uf2` (112640 bytes, UF2 family id `0xe48bff56`,
base address `0x10000000`). Checked with `file` and by reading the UF2 header.

### The Python 3.12 problem

`lib/python/qmk/math.py` used `ast.Num`, removed in Python 3.12. On Python 3.14 the
CLI died with `AttributeError: module 'ast' has no attribute 'Num'` while reading the
keyboard's `info.json`, and the makefile reported it as `Platform not defined`, which
points nowhere near the cause. Replace the removed `ast` node classes with
`ast.Constant` in that file. It is not Framework-specific and is worth sending
upstream.

## Flashing, and what it took

The module is an RP2040 with the RP2040 bootloader: entering the bootloader makes it
appear as a USB mass-storage device and the `.uf2` is copied onto it. No programmer,
no `dfu-util`, no root. Framework publishes released images, including
`framework_macropad_default_v0.3.1.uf2` and `erase_flash.uf2`, so there is a way back
from any build here.

**Getting into the bootloader is software, and the command is not VIA's.** Framework
intercepts VIA's bootloader command id (`0x0B`) in
`keyboards/framework/factory.c` and reads the *next* byte as one of their own factory
commands (`f_bootloader = 0xFE`). So the jump is:

    [0x0B, 0xFE]        over the VIA raw HID interface (hidraw, usage page 0xFF60)

Plain `[0x0B]` does nothing: their code logs "Unknown factory command: 0".
`QK_BOOT` written into the keymap over VIA also did nothing (tried twice, on layers
1-3), so that route is not worth retrying on this firmware.

**The module's RP2040 bootloader presents a partitioned volume.** It appears as
`/dev/sda1` (label `RPI-RP2`, 128M), not as a bare `/dev/sda`; mounting the whole
disk fails. The `.uf2` is copied onto the mounted volume and the bootloader does the
rest; the module reboots into the new firmware in about a second. Matching on the
`RPI-RP2` label is also the portable way to find the volume.

**Flashing resets the dynamic keymap.** 72 of 320 keycodes changed: the module came
back up running the compiled `default` keymap (Framework's numpad layout), not the
user's. The EEPROM copy was restored over VIA from `keymap-now.hex` (640 bytes, 23
chunks of `set_buffer`), verified byte-for-byte afterwards. Take a fresh dump before
every flash; `flash-macropad.py` does.

**The udev ACL does not survive re-enumeration.** After the flash, `/dev/hidraw9` was
`root:root 0600` with no ACL, even though udev's database showed the `uaccess` tag
from `/etc/udev/rules.d/99-framework-qmk-via.rules`; only root could open it, so the
host-side tool saw the module as unreadable and the panel stayed shut.
`udevadm trigger --action=add --subsystem-match=hidraw` re-applied the ACL. This
looks like a panel bug when it happens, so the script re-triggers udev before it
reports a failure to open the module.

## The layer mapping, measured

Read over the diagnostic channel with the panel's keymap, after the keymap fix below.
`layer_state` is a bitmask, so `TO(n)` shows up as `1 << n`; the layer colour is set
from the highest layer in force.

| key | layer_state | active layer | colour (hue/sat) | panel palette |
|---|---|---|---|---|
| tc0 | 1 | 0 | 128 / 255 | on |
| tc1 | 2 | 1 | 85 / 255 | off |
| tc2 | 4 | 2 | 42 / 255 | off |
| tc3 | 8 | 3 | 0 / 255 | off |

## Framework's layer hooks collide with this module's layer numbers

Framework's default macropad keymap carries `led_update_user` and
`keyboard_post_init_user` hooks that name layers by number:

```c
if (led_state.num_lock) { layer_off(_FN); } else { layer_on(_FN); }
```

`_FN` is layer 1 there. On this module the keymap lives in EEPROM and its layer 1 is
the user's tc1, so every numlock LED update reached in and cleared the layer the user
had just selected: `TO(1)` set `layer_state = 2` and the hook immediately took it
back to 0. tc1 therefore behaved like tc0, and the panel, which identifies
the layer by its colour, saw no change, so the palette stayed on for both.

The fix is `keymaps/palette/keymap.c`: Framework's keymap with every layer hook
removed (`led_update_user`, `keyboard_post_init_user`, `enable_factory_mode`). The
EEPROM keymap supplies the real layout; the compiled one only has to not interfere
with it. This is why the build uses `-km palette` and not `-km default`.

## The keymap the keypad runs

`keymap-dumps/eeprom-keymap-2026-09-16.hex` is the EEPROM keymap as it stood during
this work: the four layer keys `TO(0)`-`TO(3)` on layer 0 at matrix positions (2,1),
(2,2), (3,4) and (2,4), Framework's numpad layout around them, and modifier
combinations on the top row.

`keymap-dumps/framework-default.hex` is what a flash leaves behind: the compiled
Framework layout, with their custom keycodes on layer 1 and the RGB controls on
layer 2. Keep a copy of it, or Framework's published `default_v0.3.1.uf2`, as the way
back.

Three dumps were committed here under the names before-remap, after-remap and
their-original-layout, and all three were byte-identical, so they were the same
snapshot under three names; two of them were dropped. If the keymap has been
remapped since, re-dump it and replace the file.

## Effect on the host side

The host-side tool that drives this is not in this repo. As measured there: the panel
appears 0.09s after a layer key (it was ~1.4s while the panel waited for its poll),
and the process costs 9-13% of one core, split between the key watcher, the gate
safety net and the content refresh.
