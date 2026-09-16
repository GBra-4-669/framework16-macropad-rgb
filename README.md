# Framework 16 RGB Macropad: per-key colours for the deck panel

Firmware for the Laptop 16 RGB Macropad that colours individual keys, so the
on-screen deck panel can paint each of its cells in the same colour as the key
it stands for. A human then finds a key by matching the screen to the keypad.

**These are the files that differ from Framework's firmware, not a buildable
tree.** The build tree is `FrameworkComputer/qmk_firmware` on branch `fl16-2025`
(1.4 GB with submodules), with these files dropped into
`keyboards/framework/macropad/`. `BUILD-NOTES.md` has the whole recipe,
including the two traps that cost an evening: Framework intercepts VIA's
bootloader command and reads the *next* byte as one of their own factory
commands, and the RP2040 bootloader presents a *partitioned* volume.

| File | What it is |
|---|---|
| `keyboards/framework/macropad/panel_palette.c` | The whole addition: palette, per-key painting, and the VIA custom channel the host writes the palette through |
| `keyboards/framework/macropad/keymaps/palette/keymap.c` | Framework's default keymap with **every layer hook removed** - theirs reach into layers 1-3 by number, and the EEPROM keymap's layer 1 is the user's tc1 |
| `keyboards/framework/macropad/rules.mk` | Adds the file above to the build |
| `flash-macropad.py` | Backs up the keymap, jumps to the bootloader, flashes, restores the keymap |
| `firmware-panel-palette.uf2` | The built image |

## Why firmware

Over VIA - and over Framework's own `qmk_hid` - the only colour control is the
whole matrix's. The keyboard-specific custom channel where per-key colour would
live does not exist on the shipped firmware, which is why this exists. The
palette itself is *not* baked in: the module's copy is in RAM and the host
re-pushes it, so changing colours needs no reflash.

## What it does

* layer 0 (the panel's layer): the fifteen keys the panel maps get their own
  colour, set from the host; every other key shows the layer's colour at 30% -
  dim reads as "not a panel key" whatever the hue;
* every other layer: left completely alone, so the effect paints them as it
  always did;
* the layer colour is set on every layer change, because it is the only live
  signal the firmware exposes and the panel reads it to know which layer is on;
* read-only diagnostics on the same channel (`0xF0`, `0xF1`) report the active
  layer, the layer registers and how many times the hooks have fired.
