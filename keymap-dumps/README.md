# EEPROM keymap dumps

VIA stores the dynamic keymap in the module's EEPROM. Each dump here is 640 bytes:
10 layers x 4 matrix rows x 8 columns, 2 bytes per keycode, keycodes stored
big-endian. This is the layout the keypad runs, not the compiled
keymap in the firmware.

| File | What it is |
|---|---|
| `framework-default.hex` | what a flash leaves in EEPROM: Framework's compiled layout. Layer 0 is the numpad, layer 1 is the RGB controls, layer 2 is their factory test alphabet, and layers 3 to 9 are transparent |
| `eeprom-keymap-2026-09-16.hex` | the keymap on this module *during* the per-key colour work: `TO(0)`-`TO(3)` on layer 0 at matrix positions (2,1), (2,2), (3,4), (2,4), with Framework's numpad layout still on the rest. Not what the module runs now, and not what the panel firmware expects to find |
| `eeprom-keymap-remapped.hex` | the keymap the module actually runs: layer 0 is `TO(0)`-`TO(3)` at (2,1), (2,2), (3,4), (2,4) and `KC_NO` everywhere else, so no key types anything; layers 1-3 are transparent at those four positions and `KC_NO` elsewhere |

Reading and writing it over VIA: `id_dynamic_keymap_get_buffer` (`0x12`) and
`id_dynamic_keymap_set_buffer` (`0x13`), each with a 2-byte big-endian offset and a
length, in 23 chunks of 28 bytes except the last of 24. `flash-macropad.py` does
this before and after flashing.

Back up your own before flashing (`--dump FILE`, or run the flasher, which always
dumps first); a flash resets EEPROM to the compiled keymap, so take the dump
first.
