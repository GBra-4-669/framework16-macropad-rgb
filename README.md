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

## Where this stands (end of the 2026-09-16 session)

**Working:** the macropad's keys are individually coloured on tc0 only — fifteen
panel keys in their own colours, the reserved top row and the unused keys dim,
every other layer untouched. `deck-state` owns the palette and pushes it over the
channel this firmware adds, so the on-screen panel and the keypad are painted
from one table and cannot drift, and changing colours needs no reflash. Pressing
a keypad key fires the same action a click on its panel cell does, because the
keys are `KC_NO` on the module and `deck-state --watch-keys` reads them from the
matrix report.

**Not yet done, all small:** the panel's title could name the layer; the empty
16th cell is invisible against the theme; deck-mode previews are rendered 1:1
while the macropad's are 2×; tc2/tc3 have never been pinned by name; and the
poll costs ~0.28 s at a one-second interval, which is what makes the panel take
about a second to appear (a cheap gate-only poll would fix that).

**Where things live:** the logic is `~/.local/bin/deck-state` in the dotfiles
repo; the panel and bar icon are the `noctalia-deck` plugin repo; the firmware is
here; the build tree is `~/qmk-framework` (Framework's fork, branch `fl16-2025`,
with this directory's files dropped in — 1.4 GB, not tracked anywhere).

**The traps, all of which cost real time:**

* Framework intercepts VIA's bootloader command: the jump is `[0x0B, 0xFE]`,
  their factory command, not VIA's own. Plain `[0x0B]` is silently ignored; so is
  `QK_BOOT` written into the keymap.
* The RP2040 bootloader presents a *partitioned* volume (`/dev/sda1`, `RPI-RP2`),
  so mounting the whole disk fails.
* Flashing resets the dynamic keymap: dump it first, restore it after.
* After a re-enumeration the hidraw node can come back root-only, because
  `uaccess` does not apply on this machine; the udev rule now also grants the
  `input` group, which survives re-enumeration.
* Framework's compiled keymap hooks `layer_off(_FN)` where `_FN` is *layer 1* —
  the EEPROM keymap's tc1. Every numlock update undid the user's layer change.
  This is why the build uses `-km palette`, whose keymap has no layer hooks.
* Layer keys move `layer_state` (a bitmask: `TO(n)` is `1 << n`); the layer
  colour is set from the highest layer in force, and both `layer_state` and the
  default layer are consulted.
* VIA's raw HID carries no request id, so two writers can read each other's
  replies. `deck-state` serialises access with a lock and drains stale replies.
