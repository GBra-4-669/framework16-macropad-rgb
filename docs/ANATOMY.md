# What the patch sits on

A QMK keyboard is a stack of tables and callbacks. The three files this
repository adds or replaces are a small change to it.

## The parts, and who owns them

| Part | Where it lives in Framework's tree | This patch |
|---|---|---|
| Matrix scanning | `keyboards/framework/matrix.c`, shared by the modules; dimensions come from each keyboard's `MATRIX_ROWS` and `MATRIX_COLS` (4 by 8 on the macropad, 8 by 16 on the full keyboard). Columns are driven as GPIO, rows are read through an ADC and a mux. | untouched |
| Layout positions | `keyboards/framework/macropad/macropad.h`, a hand-written `LAYOUT` macro; `info.json` holds the physical positions | untouched |
| Compiled keymap | `keymaps/default/keymap.c`, which QMK copies into EEPROM when the stored keymap is invalid | replaced: `keymaps/palette/keymap.c`, same keys, layer hooks removed |
| Dynamic keymap | EEPROM, edited by VIA at runtime; QMK replaces it with the compiled keymap when its validity magic does not match | left alone on purpose |
| Layers | QMK core, `layer_state` is a bitmask, 16 bits wide for 10 layers here | read, to pick the layer colour |
| RGB matrix | QMK core, plus the LED tables in `macropad.c` | painted on layer 0, one callback added |
| VIA dispatch | QMK core, `quantum/via.c` | one channel handler added |
| Framework's own HID commands | `keyboards/framework/factory.c`, on command `0x0B` | the flasher uses that command; the file is untouched |

The compiled keymap and the dynamic keymap are different things. The compiled
keymap is C, built into the image, and is what QMK copies into EEPROM when the
stored one is invalid. The dynamic keymap is those 640 bytes in EEPROM, edited
by VIA at runtime.

What makes the stored keymap invalid is a magic derived from the date digits of
the build date (`quantum/via.c`, `via_eeprom_is_valid`). A build on another date
changes it, so the first boot after such a rebuild starts from the compiled
keymap. Reflashing the same image
leaves the magic alone and keeps the stored keymap. The emulated EEPROM lives in
the top of the 1 MiB flash, above the image, so writing the image does not
overwrite it.

The tree, with the files this patch adds or replaces marked:

    keyboards/framework/
    ├── rules.mk            VIA on, backlight, custom matrix, SRC += matrix.c ...
    ├── framework.c         shared by every Framework input module
    ├── factory.c           Framework's factory commands, including the bootloader jump
    ├── matrix.c            the shared ADC matrix scanner
    └── macropad/
        ├── info.json       processor, USB ids, physical positions
        ├── macropad.h      the LAYOUT macro
        ├── config.h        MATRIX_ROWS 4, MATRIX_COLS 8, 24 LEDs, driver
        ├── macropad.c      g_is31_leds, g_led_config, one init hook
        ├── rules.mk        RGB matrix on + SRC += panel_palette.c        (replaced)
        ├── panel_palette.c the whole patch                                (added)
        └── keymaps/
            ├── default/    Framework's keymap, with the layer hooks
            └── palette/    the same keymap without the hooks             (added)

Every `.c` listed in `SRC` is compiled into the firmware, and QMK calls the
callbacks it finds at link time.

## `_kb` and `_user`

QMK has two levels of the same callback: `layer_state_set_kb` at the keyboard
level and `layer_state_set_user` for the keymap. The core ships weak defaults
for the `_kb` versions that call the `_user` ones, so a keyboard can implement a
callback without preventing a keymap from implementing its own.

A keyboard-level definition wins at link time. That is why `panel_palette.c` can
change layer and paint behaviour without including anything, without patching
QMK, and without editing Framework's `macropad.c`: it defines callbacks the core
was already going to call. It also means its `_kb` functions replace the weak
defaults rather than chain to them, which is listed as a limit in the README.

## Reading `panel_palette.c`

`panel_palette.c`, in the order it is written:

1. **The tables.** `PANEL_ROWS`, `PANEL_COLS`, the cell count, `PANEL_DIM`, and
   `layer_hue[]`. Nothing here runs, it is the vocabulary the rest uses.
2. **`panel_led` and `panel_rgb`.** The first maps a panel cell to an LED index
   and comes from `g_led_config` in `macropad.c`. The second is the colour store
   the host writes into. One is fixed, one is the palette.
3. **The two layer hooks.** `layer_state_set_kb` and
   `default_layer_state_set_kb` both exist because a keymap can move either
   register, and the colour has to follow whichever one it used.
4. **The paint pass.** `rgb_matrix_indicators_advanced_kb` runs after the
   configured effect has filled the LED buffer. It returns early unless layer 0
   is active; otherwise it dims every LED and then paints the fifteen panel
   cells.
5. **The VIA handler.** `via_custom_value_command_kb` receives the 32-byte
   request buffer, and its reply is that same buffer with the answer bytes
   filled in. `value_id` is the cell, first three data bytes are red, green and
   blue. The same function answers the read-only `0xF0` and `0xF1` diagnostics
   from the live layer state.

The two halves never call each other:

    host program
        │  32-byte raw HID report
        ▼
    via_custom_value_command()            QMK
        │  channel 0
        ▼
    via_custom_value_command_kb()         this patch: writes panel_rgb[][]
        │
        ▼
    panel_rgb[4][4][3]                    the only interface between the halves
        ▲
        │
    rgb_matrix_indicators_advanced_kb()   this patch: reads it, on every frame
        │
        ▼
    rgb_matrix_set_color() -> LED buffer -> IS31FL3743A driver -> 24 LEDs

The host-side program does not know the firmware exists beyond a cell number and
three bytes, and the firmware does not know what the host is drawing. Any host
that can send those reports can colour the keypad.

The diagnostics take the other direction: `0xF0` and `0xF1` read `layer_state`
and `default_layer_state` and report the layer in force, which is how the host
tells "the keypad did not change layer" from "the firmware did not notice".

## The numbers that look arbitrary

* There are 10 dynamic keymap layers, so QMK sets `MAX_LAYER` to 10 and picks a
  16-bit `layer_state_t`: layers 0 to 9 exist and 9 is the highest. The register
  is wider than the layer count. `panel_layer_of()` counts down from 15, above
  both; the bits that can match are the low ones. It stops at 1 because layer 0
  is the fallback, not something set by a layer key.
* The four layer hues are 128, 85, 42 and 0 out of 255, which is about 180, 120,
  59 and 0 degrees: roughly 60 degrees apart, a cool to warm ramp, so the layer
  order is visible on the keypad itself.
* `PANEL_DIM` is 30 percent because it looked right on the module. It was chosen,
  not measured.
* `panel_active_layer()` asks both `layer_state` and `default_layer_state` and
  takes the higher one, because `TO()` and `DF()` move different registers and
  either one can be the layer in force.
* The `>= PANEL_CELLS` check in the VIA handler refuses value ids from 16 up.
  Cell 15 is inside the 4 by 4 grid but outside the panel, so it is accepted,
  stored and left to the dim pass.
