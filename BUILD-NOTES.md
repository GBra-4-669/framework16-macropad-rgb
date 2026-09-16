# Building the macropad firmware on this machine

This tree is **Framework's own QMK fork** (`FrameworkComputer/qmk_firmware`),
branch `fl16-2025`, shallow-cloned with shallow submodules. That branch is where
the Laptop 16 modules' keyboards live (`keyboards/framework/macropad`); upstream
QMK master does not have them.

It is here because the on-screen deck panel wants to paint each key its own
colour and match the physical keypad's LEDs, and the shipped firmware has no way
to do that: over VIA (and over Framework's `qmk_hid`) the only colour control is
the whole matrix's. Per-key colour has to come from firmware.

## Toolchain

Installed from Fedora, machine-wide:

    arm-none-eabi-gcc-cs arm-none-eabi-gcc-cs-c++ arm-none-eabi-binutils-cs arm-none-eabi-newlib

The QMK CLI is **not** installed system-wide: Fedora's Python is externally
managed and QMK is not packaged. It lives in its own venv, which is also where
the repo's `requirements.txt` went:

    python3 -m venv ~/.local/share/qmk-venv
    ~/.local/share/qmk-venv/bin/pip install qmk -r requirements.txt

## Build

    cd ~/qmk-framework
    QMK_HOME=$PWD ~/.local/share/qmk-venv/bin/qmk compile -kb framework/macropad -km default

Output: `framework_macropad_default.uf2` (112640 bytes, family id 0xe48bff56,
base address 0x10000000). Verified with `file` and by reading the UF2 header.

## Local patch, applied to this tree only

`local-patches/0001-python312-remove-ast-num.patch` — `lib/python/qmk/math.py`
used `ast.Num`, removed in Python 3.12, so on this machine's Python 3.14 the CLI
died with `AttributeError: module 'ast' has no attribute 'Num'` while reading the
keyboard's info.json. The makefile reported it as `Platform not defined`, which
points nowhere near the cause. Nothing Framework-specific; worth sending upstream.

## Flashing (not done yet)

The module is an RP2040 with the RP2040 bootloader: entering the bootloader makes
it appear as a USB mass-storage device and the `.uf2` is copied onto it. No
programmer, no dfu-util, no root. Framework publishes released images, including
`framework_macropad_default_v0.3.1.uf2` and `erase_flash.uf2`, so there is a way
back from any build here.

## What is NOT in this tree yet

No per-key colour code. That is the next step: colour the 15 keys that map to the
panel's grid, leave the reserved top row and the unused keys on the layer colour,
and expose the palette so the host can set it (otherwise every palette change
needs a reflash, which is the thing being avoided).

## Flashed: 2026-09-16, and what it took

**Getting into the bootloader is software, and the command is not VIA's.**
Framework intercepts VIA's bootloader command id (0x0B) in
`keyboards/framework/factory.c` and reads the *next* byte as one of their own
factory commands (`f_bootloader = 0xFE`). So the jump is:

    [0x0B, 0xFE]        over the VIA raw HID interface (hidraw, usage page 0xFF60)

Sending plain `[0x0B]` does nothing: their code logs "Unknown factory command: 0".
`QK_BOOT` written into the keymap over VIA also did nothing (twice, on layers 1-3),
so that route is not worth retrying on this firmware.

**The module's RP2040 bootloader presents a partitioned volume.**
It appears as `/dev/sda1` (label RPI-RP2, 128M), **not** as a bare `/dev/sda` -
mounting the whole disk fails. The .uf2 is copied onto the mounted volume and the
bootloader does the rest; the module reboots into the new firmware in about a second.

**Flashing resets the dynamic keymap.** 72 of 320 keycodes changed: the module came
back up running the compiled `default` keymap (Framework's numpad layout), not the
user's. The EEPROM copy was restored over VIA from `~/f16-macropad/keymap-now.hex`
(640 bytes, 23 chunks of `set_buffer`), verified byte-for-byte afterwards. Expect to
do this after every flash - take a fresh dump first.

**The udev ACL does not survive re-enumeration.** After the flash, `/dev/hidraw9`
was `root:root 0600` with no ACL even though udev's database showed the `uaccess`
tag from `/etc/udev/rules.d/99-framework-qmk-via.rules`; only root could open it, so
`deck-state` (which runs as the user) saw the module as unreadable and the panel
stayed shut. `udevadm trigger --action=add --subsystem-match=hidraw` re-applied the
ACL. Worth knowing because a panel that silently cannot read the module looks like a
panel with a bug in it.

## The layer mapping, measured (2026-09-16)

Measured over the diagnostic channel with the panel's keymap, after the keymap
fix below. `layer_state` is a *bitmask*, so TO(n) shows up as `1 << n`, and the
layer colour is set from the highest layer in force:

| key | layer_state | active layer | colour (hue/sat) | palette |
|---|---|---|---|---|
| tc0 | 1 | 0 | 128 / 255 | on |
| tc1 | 2 | 1 | 85 / 255 | off |
| tc2 | 4 | 2 | 42 / 255 | off |
| tc3 | 8 | 3 | 0 / 255 | off |

## Framework's layer hooks collide with this module's layer numbers

Framework's default macropad keymap - compiled into every build - carries
`led_update_user` and `keyboard_post_init_user` hooks that name layers by
number:

```c
if (led_state.num_lock) { layer_off(_FN); } else { layer_on(_FN); }
```

`_FN` is layer **1** there. On this module the keymap lives in EEPROM and its
layer 1 is the user's **tc1**, so every numlock LED update reached in and
cleared the layer the user had just selected: `TO(1)` set `layer_state = 2` and
the hook immediately took it back to 0. tc1 therefore behaved exactly like tc0,
and the panel - which identifies the layer by its colour - saw no change, so the
palette stayed on for both.

The fix is `keymaps/palette/keymap.c`: Framework's keymap with every layer hook
removed (`led_update_user`, `keyboard_post_init_user`, `enable_factory_mode`).
The EEPROM keymap supplies the real layout; the compiled one only has to not
interfere with it. This is why the build uses `-km palette` and not `-km default`.
