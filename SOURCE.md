# Source for the firmware image

`firmware-panel-palette.uf2` is a binary that contains GPL-2.0-or-later code from
QMK and from Framework Computer, plus the files in this repository. Everything
that went into it is listed below, so the source can be reconstructed.

## The tree it was built from

Base: [FrameworkComputer/qmk_firmware](https://github.com/FrameworkComputer/qmk_firmware),
branch `fl16-2025`, commit `11c49dbeef03c853bbd3a783810d4ba7d29cb287`
(2025-08-21, "fl16: Bump version to 0.3.1"). The keyboard definition is only on
that branch.

The submodules at that commit:

| Submodule | Commit |
|---|---|
| `lib/chibios` | `11edb1610980f213b9f83161e1715a46fb7e4c51` |
| `lib/chibios-contrib` | `da78eb3759b8d1779b237657c7667baa4aa95ca1` |
| `lib/googletest` | `e2239ee6043f73722e7aa812a459f54a28552929` |
| `lib/lufa` | `549b97320d515bfca2f95c145a67bd13be968faa` |
| `lib/lvgl` | `e19410f8f8a256609da72cff549598e0df6fa4cf` |
| `lib/pico-sdk` | `a3398d8d3a772f37fef44a74743a1de69770e9c2` |
| `lib/printf` | `c2e3b4e10d281e7f0f694d3ecbd9f320977288cc` |
| `lib/vusb` | `819dbc1e5d5926b17e27e00ca6d3d2988adae04e` |

Get them with:

    git clone --branch fl16-2025 https://github.com/FrameworkComputer/qmk_firmware.git
    cd qmk_firmware
    git checkout 11c49dbeef03c853bbd3a783810d4ba7d29cb287
    git submodule update --init

## The files from this repository

Copied into `keyboards/framework/macropad/`:

* `keyboards/framework/macropad/panel_palette.c` (new)
* `keyboards/framework/macropad/rules.mk` (replaces Framework's two-line file)
* `keyboards/framework/macropad/keymaps/palette/keymap.c` (new keymap)

## The tree patches

Two patches go on the tree before the build, and both are QMK's. They are not
committed here.

The first is for Python 3.12 and later, where `ast.Num` no longer exists. In
`lib/python/qmk/math.py`:

    -        if isinstance(node, ast.Num):
    -            return node.n
    +        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
    +            return node.value

The second pins the build date. QMK writes the wall-clock time into
`QMK_BUILDDATE`, which lands in the image and seeds the EEPROM validity magic.
In `lib/python/qmk/cli/generate/version_h.py`:

    -from time import strftime
    +from time import strftime, gmtime
    +import os

         if cli.args.skip_all:
             current_time = "1970-01-01-00:00:00"
    +    elif os.environ.get('SOURCE_DATE_EPOCH'):
    +        current_time = strftime(TIME_FMT, gmtime(int(os.environ['SOURCE_DATE_EPOCH'])))
         else:
             current_time = strftime(TIME_FMT)

[docs/BUILD.md](docs/BUILD.md#the-python-312-trap) explains the first one and the
reproducibility section below uses the second.

## The build

Built from the files in this repository, with the tree and patches above, on
Fedora 44 with `arm-none-eabi-gcc` 15.2.0, the QMK CLI 1.2.0 and Python 3.14.7.
The date is pinned, so the output does not depend on when the build runs:

    export TZ=UTC
    export SOURCE_DATE_EPOCH=1793880000     # 2026-11-05 12:00:00 UTC
    QMK_HOME=$PWD ~/.local/share/qmk-venv/bin/qmk compile \
        -kb framework/macropad -km palette

The result was renamed from `framework_macropad_palette.uf2` to
`firmware-panel-palette.uf2`. Its sha256 is in
`firmware-panel-palette.uf2.sha256` and in the v0.1.0 release.

## Reproducibility

The image is bit-for-bit reproducible with the recipe above: two clean builds on
Fedora 44 with `arm-none-eabi-gcc` 15.2.0 and QMK CLI 1.2.0 produced the shipped
sha256, `2be0da7781750e0062dbb585dcfd7aa50cae40c28cab54201eb7e86479f05cc2`. The
build used `QMK_BUILDDATE` `2026-11-05-12:00:00`, and the EEPROM magic derives
from the date digits in it; without the second patch above the date would be the
wall-clock time and nothing would match.

Because the date is pinned, the EEPROM validity magic is stable: reflashing this
image, or rebuilding it with this command, leaves the stored keymap alone. A
build with another compiler or QMK CLI can produce different bytes; a build on
another date also changes the magic and resets the keymap once.


## Written offer

This is a written offer, valid for three years from the date of the v0.1.0
release, to give anyone who asks the complete corresponding source for the
published image, under GPLv2 section 3(b). That means a source archive of the
tree at the pinned commit, the submodules at the commits listed above, the files
from this repository, the two tree patches, and the licence texts of everything
linked into the image. Open an issue on this repository and I will make it
available.

The pinned commit, the submodule list and the patches above are written out in
full so the tree can be rebuilt without asking.

## Licence

The image and this repository are GPL-2.0-or-later. The image also contains
ChibiOS (GPL-3.0), the Raspberry Pi Pico SDK (BSD-3-Clause) and small MIT and BSD
licensed libraries, all picked up by QMK's build for the RP2040. Their licence
files are in the tree under `lib/`. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
