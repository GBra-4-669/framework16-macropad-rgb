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

## The one tree patch

The build tree still calls `ast.Num`, which Python 3.12 removed. The build was
made with this change applied to `lib/python/qmk/math.py`, and it is not part of
this repository because it belongs to QMK:

    -        if isinstance(node, ast.Num):
    -            return node.n
    +        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
    +            return node.value

[docs/BUILD.md](docs/BUILD.md#the-python-312-trap) explains it, including the
misleading error message it causes.

## The build

    QMK_HOME=$PWD ~/.local/share/qmk-venv/bin/qmk compile \
        -kb framework/macropad -km palette

The result was renamed from `framework_macropad_palette.uf2` to
`firmware-panel-palette.uf2`. Its sha256 is in
`firmware-panel-palette.uf2.sha256` and in the v0.1.0 release.

## What the image is not

It is not bit-for-bit reproducible from the steps above. The build happened on
Fedora 43 in September 2026
and the exact `arm-none-eabi-gcc` version was not recorded. A rebuild with a
different toolchain will produce different bytes.

The edits after the build changed comments, documentation, one unused static
variable in `panel_palette.c` and one shift in the same file from `1` to `1u`,
which makes it well defined for shifts above the register width without changing
the value it produces. None of those change what the firmware
does, but they mean the tree in this repository and the tree that was compiled
are not textually identical.

## Written offer

This is a written offer, valid for three years from the date of the v0.1.0
release, to give anyone who asks the complete corresponding source for the
published image. That means a source archive of the tree at the pinned commit,
the submodules at the commits listed above, the files from this repository, the
tree patch, and the licence texts of everything linked into the image. Open an
issue on this repository and I will make it available.

The pinned commit, the submodule list and the patch above are written out in
full so the tree can be rebuilt without asking.

## Licence

The image and this repository are GPL-2.0-or-later. The image also contains
ChibiOS (GPL-3.0), the Raspberry Pi Pico SDK (BSD-3-Clause) and small MIT and BSD
licensed libraries, all picked up by QMK's build for the RP2040. Their licence
files are in the tree under `lib/`. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
