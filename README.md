# Framework 16 RGB Macropad: per-key colours from the host

> [!WARNING]
> Flashing replaces the firmware on the macropad. It is recoverable: Framework
> publishes its stock macropad images and an `erase_flash.uf2`, and the module enters
> an RP2040 bootloader that appears as a USB drive. Two things catch people out:
>
> * **A flash resets the EEPROM keymap** to the compiled default. Back yours up
>   first; `flash-macropad.py` does that automatically and restores it afterwards.
> * **The flasher uses `sudo`** to mount the volume it finds by the `RPI-RP2` label
>   and to copy the image onto it. It matches your module by USB id (`32ac:0013`),
>   but read the script before running it and check the volume yourself with
>   `lsblk -o NAME,LABEL` if you want to see what it writes to.
>
> This is a worked example from one module, not supported firmware and not a
> Framework release. The notes describe what went wrong and how it was found, which
> is the part that transfers to other keyboards.

Adds a VIA custom channel to the Framework Laptop 16 RGB Macropad so the host can
colour keys individually while the keyboard is running. The use case here is a deck
panel: the panel paints its cells from a palette, pushes the same palette to the
keypad, and the key that runs a cell can be found by its colour instead of by
position.

Framework's shipped firmware cannot do this. It does not implement VIA's
keyboard-specific custom channel, and `rgb_matrix` channel 3 holds one colour for
the whole matrix. Framework's own `qmk_hid` has the same ceiling. Per-key colour
has to come from firmware.

![The deck panel and the macropad showing the same colours](docs/macropad-and-panel.jpg)

![The deck panel UI that drives it](docs/deck-panel.png)

## What is in here

These are the files that differ from Framework's fork of QMK, not a buildable tree.
Copy them into that tree, then build; see [Build](#build) for the commands.

| Path | Contents |
|---|---|
| `keyboards/framework/macropad/panel_palette.c` | per-key palette, layer colour, the VIA custom channel and its diagnostics |
| `keyboards/framework/macropad/keymaps/palette/keymap.c` | Framework's default keymap with the layer hooks removed, see [The layer-hook collision](#the-layer-hook-collision) |
| `keyboards/framework/macropad/rules.mk` | puts `panel_palette.c` in the build |
| `flash-macropad.py` | keymap backup, bootloader jump, flash, keymap restore |
| `firmware-panel-palette.uf2` | the built image |
| `keymap-dumps/` | EEPROM keymap dumps, and the format they use |
| `udev/99-framework-macropad-via.rules` | hidraw access as a normal user |
| `BUILD-NOTES.md` | toolchain, build commands and the traps, in full |

## Build

Framework's macropad keyboard definitions live on their own branch, not in upstream
QMK, so that branch is the build tree:

    git clone --branch fl16-2025 --depth 1 \
        https://github.com/FrameworkComputer/qmk_firmware.git ~/qmk-framework
    cd ~/qmk-framework
    git submodule update --init --depth 1
    python3 -m venv ~/.local/share/qmk-venv
    ~/.local/share/qmk-venv/bin/pip install qmk -r requirements.txt

Then copy this repo's files into the tree and compile. The tree's `macropad`
directory already exists, so copy into it rather than over it:

    K=~/qmk-framework/keyboards/framework/macropad
    cp <this repo>/keyboards/framework/macropad/panel_palette.c $K/
    cp <this repo>/keyboards/framework/macropad/rules.mk $K/
    cp -r <this repo>/keyboards/framework/macropad/keymaps/palette $K/keymaps/
    cd ~/qmk-framework
    QMK_HOME=$PWD ~/.local/share/qmk-venv/bin/qmk compile -kb framework/macropad -km palette

The result is `framework_macropad_palette.uf2`. `arm-none-eabi-gcc` has to be
installed (on Fedora: `arm-none-eabi-gcc-cs arm-none-eabi-binutils-cs
arm-none-eabi-newlib`).

On Python 3.12 and later the QMK CLI stops while reading the keyboard's `info.json`
with `AttributeError: module 'ast' has no attribute 'Num'`, and reports it as
`Platform not defined`, which points nowhere near the cause. The fix is in
`lib/python/qmk/math.py`, where `ast.Num` no longer exists: use `ast.Constant`. It
is not Framework-specific, and belongs upstream.

## Flash

Install the udev rule first, or the module's hidraw node will not be readable as
your user:

    sudo cp udev/99-framework-macropad-via.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules && sudo udevadm trigger

Then, as your user (only the mount and the copy use `sudo`):

    python3 flash-macropad.py                  # flash firmware-panel-palette.uf2
    python3 flash-macropad.py other.uf2        # flash any other image
    python3 flash-macropad.py --status         # print state, change nothing

The script saves the EEPROM keymap before it touches anything, because a flash
resets it to the compiled default, and writes it back afterwards. The copy is
verified by sha256. The script prints what it is about to do and waits for you to type `flash` before it
jumps to the bootloader; `--yes` skips that prompt, `--backup-dir` chooses where the
dumps go, and `--no-deck` skips the host-side tool at the end.

## The VIA channel

`panel_palette.c` implements custom channel 0, which the shipped firmware leaves
unimplemented. Values are addressed by `value_id`, with `command_id` saying whether
it is a read or a write:

| `value_id` | `id_custom_set_value` | `id_custom_get_value` |
|---|---|---|
| 0-15 | set that cell's RGB | read that cell's RGB |
| 0xF0 | - | active layer, layer changes since boot, `layer_state & 0xFF` |
| 0xF1 | - | the same three, for `default_layer_state` |

Cells are numbered row-major, `row * 4 + col`; cell 15 has no key behind it.
`id_custom_save` is accepted and does nothing. The palette lives in RAM and belongs
to the host: persisting a copy in EEPROM would let the keypad show colours the panel
no longer uses, if the host's table changed while the keypad was unplugged.
Anything the firmware does not handle comes back as `id_unhandled`.

## Layer colour and the layer keys

The module reports its active layer as an RGB colour on VIA's own rgb channel. That
channel is the live signal the shipped firmware already exposes, and the panel reads
it to know which layer is selected. The colour is set from the higher of
`layer_state` and `default_layer_state`, so keymaps that move either one work.

`rgb_matrix_indicators_advanced_kb` only paints layer 0. On other layers the matrix
is left to the configured effect, so the panel's palette does not bleed into layers
the panel is not showing.

The four keys that select layers are `TO(0)`-`TO(3)` at matrix positions (2,1),
(2,2), (3,4) and (2,4) on layer 0. The EEPROM keymap can be replaced over VIA at any
time without rebuilding; `keymap-dumps/` has examples of the format.

## The layer-hook collision

Framework's default keymap carries `led_update_user` and `keyboard_post_init_user`
hooks that name layers by number, and `_FN` is layer 1 there:

```c
if (led_state.num_lock) { layer_off(_FN); } else { layer_on(_FN); }
```

This module is driven from an EEPROM keymap whose layer 1 is the user's tc1, so
every numlock update cleared the layer the user had just selected. `TO(1)` set
`layer_state = 2` and the hook took it straight back to 0, which made tc1 behave
like tc0. `keymaps/palette/keymap.c` is Framework's keymap with those hooks removed:
the EEPROM keymap supplies the real layout, and the compiled one only has to leave
it alone. That is why the build uses `-km palette`.

## Traps

The long version, with the session log, is in `BUILD-NOTES.md`.

* **The bootloader jump is a Framework factory command.** Over the VIA raw HID
  interface it is `[0x0B, 0xFE]`. Framework intercepts command `0x0B` in
  `keyboards/framework/factory.c` and reads the next byte as one of their own
  commands. Plain `[0x0B]` is ignored, and `QK_BOOT` written into the keymap does
  nothing.
* **The RP2040 bootloader appears as a partition** (`/dev/sda1`, label `RPI-RP2`),
  so mounting the whole disk fails. The label is also the reliable way to find it.
* **Flashing resets the dynamic keymap** to the compiled default. Dump it first and
  restore it afterwards; the script does both.
* **`uaccess` did not survive re-enumeration** on the machine this was written on,
  so hidraw came back as `root:root 0600`. The udev rule here grants the `input`
  group as well, and the script re-triggers udev before giving up.
* **VIA's raw HID carries no request id**, so two writers can read each other's
  replies. The host-side tool serialises access with a lock and drains stale replies.

## Checking it worked

`--status` prints the layer colour and the diagnostics, so a colour that did not
change can be told apart from a module that never changed layer:

    $ python3 flash-macropad.py --status
    macropad at /dev/hidraw9
    layer colour (hue, sat): (128, 255)
    layer/changes/state: (0, 4, 1)
    default layer/changes/state: (0, 1, 1)
    cell 0: (255, 0, 0)

## Not done

* the panel title does not name the layer;
* the empty 16th cell is invisible against the panel's theme;
* deck-mode previews are rendered 1:1 while the macropad's are rendered 2x;
* tc2 and tc3 have not been pinned by name.

## Licence and credits

`panel_palette.c` and `keymap.c` are GPL-2.0-or-later; see `LICENSE`.
`keymap.c` is Framework's own keymap with the layer hooks removed.
The keyboard definitions under `keyboards/framework/macropad/` come from
[FrameworkComputer/qmk_firmware](https://github.com/FrameworkComputer/qmk_firmware),
branch `fl16-2025`, which is a fork of [QMK](https://github.com/qmk/qmk_firmware).
`firmware-panel-palette.uf2` is built from that tree; `BUILD-NOTES.md` has the
recipe.
