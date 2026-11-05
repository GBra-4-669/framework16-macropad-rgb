# Build

This repository is not a buildable QMK tree. It holds the files that differ from
Framework's fork, and the build happens inside that fork. The commands below
were checked on Fedora 44 with `arm-none-eabi-gcc` 15.2.0 and the QMK CLI 1.2.0;
I have not built it on another distribution. The shipped image was rebuilt from
this source and tested on the module, and that toolchain reproduces it
byte-for-byte.

## What the build makes

The build produces one UF2 image for the macropad. The module is an RP2040 with 264 KiB of SRAM and
1 MiB of QSPI flash for the firmware, plus an IS31FL3743A LED driver behind the
24 keys. QMK's RP2040 target produces a UF2 image, which is the format the RP2040
bootloader accepts over USB mass storage.

## The build tree

The macropad's keyboard definition is not in upstream QMK. It lives in
[FrameworkComputer/qmk_firmware](https://github.com/FrameworkComputer/qmk_firmware)
on the `fl16-2025` branch, so that branch is the tree.

    git clone --branch fl16-2025 \
        https://github.com/FrameworkComputer/qmk_firmware.git ~/qmk_firmware
    cd ~/qmk_firmware
    git checkout 11c49dbeef03c853bbd3a783810d4ba7d29cb287
    git submodule update --init --depth 1

The branch currently points at `11c49db`; the checkout pins it rather than
trusting the tip to stay there. That commit is 2025-08-21, "fl16: Bump version to
0.3.1". A different commit is a different tree and will not build this image's
source.

## Toolchain

The cross compiler comes from the distribution. On Fedora:

    sudo dnf install arm-none-eabi-gcc-cs arm-none-eabi-gcc-cs-c++ \
        arm-none-eabi-binutils-cs arm-none-eabi-newlib

On Debian and Ubuntu the packages are `gcc-arm-none-eabi`,
`binutils-arm-none-eabi` and `libnewlib-arm-none-eabi`, but I have not built
there and cannot promise the versions line up.

The QMK CLI is not packaged for Fedora, because Fedora's Python is externally
managed and pip will not install into it. A venv solves that and keeps the
build tree's Python requirements out of the system. Run this from the root of
the tree, because `requirements.txt` is the tree's:

    cd ~/qmk_firmware
    python3 -m venv ~/.local/share/qmk-venv
    ~/.local/share/qmk-venv/bin/pip install qmk
    ~/.local/share/qmk-venv/bin/pip install -r requirements.txt

Use the venv's `qmk` afterwards. `arm-none-eabi-gcc` still has to be on `PATH`.

## Copying the files in

The files that go into `keyboards/framework/macropad/` in the tree are listed
below. The directory already exists there, so copy into it; do not copy the whole `keyboards/`
directory from this repo over the tree, which would replace files this patch
does not touch.

| File here | Where it goes | What to do |
|---|---|---|
| `keyboards/framework/macropad/panel_palette.c` | `keyboards/framework/macropad/panel_palette.c` | new file |
| `keyboards/framework/macropad/rules.mk` | `keyboards/framework/macropad/rules.mk` | replace |
| `keyboards/framework/macropad/keymaps/palette/keymap.c` | `keyboards/framework/macropad/keymaps/palette/keymap.c` | new keymap |

Framework's `rules.mk` is two lines (`RGB_MATRIX_ENABLE`, `RGB_MATRIX_DRIVER`).
The copy here is those two lines plus one `SRC += panel_palette.c`, so replacing
it is safe. The keymap is a new directory next to Framework's `default`.

With this repo checked out somewhere, from the build tree:

    R=/path/to/framework16-macropad-rgb
    K=keyboards/framework/macropad
    cp $R/$K/panel_palette.c $K/
    cp $R/$K/rules.mk $K/
    mkdir -p $K/keymaps/palette
    cp $R/$K/keymaps/palette/keymap.c $K/keymaps/palette/

## Compiling

The two exports pin the build date. With them and the toolchain above, the
output is the shipped image:

    cd ~/qmk_firmware
    export TZ=UTC
    export SOURCE_DATE_EPOCH=1793880000     # 2026-11-05 12:00:00 UTC
    QMK_HOME=$PWD ~/.local/share/qmk-venv/bin/qmk compile \
        -kb framework/macropad -km palette

`QMK_HOME` is needed because the `qmk` command otherwise looks for the tree in
the default location. The command runs `make` underneath, so the usual QMK
messages are what you will see: it generates the make rules from `info.json`,
compiles QMK and the keyboard, links, then converts the ELF into
`framework_macropad_palette.uf2` in the tree's root. The copy in this repo is
that file under a different name, `firmware-panel-palette.uf2`, so the flasher
and the docs do not depend on QMK's naming.

## Checking the image

The image in this repo is 113,664 bytes, and each 512-byte UF2 block carries a
256-byte payload, so 222 blocks.

    $ file framework_macropad_palette.uf2
    framework_macropad_palette.uf2: UF2 firmware image, family Raspberry Pi RP2040, base address 0x10000000, 222 total blocks
    $ stat -c %s framework_macropad_palette.uf2
    113664
    $ sha256sum framework_macropad_palette.uf2
    2be0da7781750e0062dbb585dcfd7aa50cae40c28cab54201eb7e86479f05cc2  ...

That sha256 is the shipped image, and the build above reproduces it
byte-for-byte on Fedora 44 with `arm-none-eabi-gcc` 15.2.0 and the QMK CLI 1.2.0:
two clean builds produced this exact file. A different compiler or QMK CLI can
produce different bytes, so compare a rebuild against it only when the toolchain
matches. [SOURCE.md](../SOURCE.md) records the commit, the submodules and the
tree patches.

The palette code is the same one that was checked on the module: all sixteen
cells answer with the palette table in `panel_palette.c`, cell 16 answers
`0xff`, the layer colour reads `(128, 255)` after boot, `0xF0` reports the layer
and its change counter, and the 640-byte keymap reads back unchanged after the
flash that wrote it.

This image also carries three fixes, each measured on the module: RGB brightness
stayed at 39 across a reboot and three boot-time layer changes (it used to jump
to 255); a probe keymap's `layer_state_set_user` was called and reported layer 3
(it used to be ignored); and after a forced keymap reset the compiled keymap
contains `LT(_FN, KC_NUM)` (0x4153) at matrix position (0,0), so holding Num
reaches the RGB layer.

If you want to look at the header yourself, the first 32 bytes are little-endian
`magic0, magic1, flags, target address, payload size, block number, block count,
family id`:

    python3 -c 'import struct, sys; print([hex(x) for x in struct.unpack("<IIIIIIII", open(sys.argv[1], "rb").read(32))])' \
        framework_macropad_palette.uf2

For an RP2040 image, `magic0` is `0x0a324655` (the bytes `UF2\n`), the target
address is `0x10000000` (where the RP2040's QSPI flash is mapped), and the family
id is `0xe48bff56`.

## The build date and reproducibility

QMK writes the wall-clock time into the image as `QMK_BUILDDATE`, from
`lib/python/qmk/cli/generate/version_h.py`, and the EEPROM validity magic is
derived from the date digits in that string. Two builds at different times
therefore differ, and the first boot after a build on another date starts from
the compiled keymap.

The date can be pinned, as reproducible builds normally do, with
`SOURCE_DATE_EPOCH`. Patch that file:

    -from time import strftime
    +from time import strftime, gmtime
    +import os

         if cli.args.skip_all:
             current_time = "1970-01-01-00:00:00"
    +    elif os.environ.get('SOURCE_DATE_EPOCH'):
    +        current_time = strftime(TIME_FMT, gmtime(int(os.environ['SOURCE_DATE_EPOCH'])))
         else:
             current_time = strftime(TIME_FMT)

and build with the date fixed:

    export TZ=UTC
    export SOURCE_DATE_EPOCH=1793880000     # 2026-11-05 12:00:00 UTC

The shipped image was built with the date pinned to `2026-11-05-12:00:00` in
the generated `version.h`; the image itself carries the EEPROM magic derived from
the date digits, not the string. Those digits are what the keymap depends on: a
build on another day changes the magic and resets the keymap once, while a
rebuild on the same day keeps it.

## The Python 3.12 trap

On Python 3.12 and later, QMK stops while reading the keyboard's `info.json`:

    AttributeError: module 'ast' has no attribute 'Num'

`lib/python/qmk/math.py` in Framework's branch still walks the syntax tree with
`ast.Num`, which Python 3.12 removed. The CLI dies there, and the makefile
reports it much later as

    builddefs/build_keyboard.mk:195: *** Platform not defined.

which points nowhere near the cause. The fix is in that file, around the
`ast.Num` check:

    -        if isinstance(node, ast.Num):
    -            return node.n
    +        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
    +            return node.value

`ast.Num` was deprecated in 3.8 and removed in 3.12; `ast.Constant` covers the
same nodes and has been the right node since 3.8.

Running the whole build in a Python 3.11 venv avoids the problem entirely, and
is less to explain to the next person. I did the patch because the venv was
already on 3.14 and I wanted to know what was actually breaking.

That file no longer exists in upstream QMK under that name:
[PR #25038](https://github.com/qmk/qmk_firmware/pull/25038) (November 2025) moved
`lib/python/qmk/math.py` to `math_ops.py` and made the same `ast.Constant`
change there. It matters here because the fix is to Framework's pinned branch,
not to QMK.

## Why the build uses `-km palette`

The compiled keymap has to leave the EEPROM keymap alone. Framework's default
keymap carries a `led_update_user` hook that names layers by number, and on a
keymap whose layer 1 is a user layer it fights it. `keymaps/palette/keymap.c` is
Framework's keymap with that hook and `enable_factory_mode` removed, and building
with `-km default` puts them back. The measured evidence is in
[the session log](session-2026-09-16.md#the-layer-hook-collision).

## Tests

The flasher's pure functions have tests, and they do not need hardware:

    python3 -m pytest -q

They cover the UF2 block checks, the keymap file parsing, the `lsblk` walk and
the reply matching in `Via.ask`. One of them checks the shipped image against
its `.sha256`, so a modified image fails the suite. `.github/workflows/tests.yml`
runs them on Python 3.11, 3.12 and 3.13. Nothing here tests the firmware itself;
that needs the module.

