# The palette protocol

A host can implement this without the rest of the project. The panel and the
keypad agree on colours because the host writes them over VIA's raw HID
interface, into a keyboard-specific channel that Framework's shipped firmware
does not implement.

## The transport

VIA talks to the keyboard over raw HID, and every report is 32 bytes in both
directions. The first byte is the command, and the keyboard replies by sending
the request buffer back with the answer bytes filled in. There is no request id.
The custom-value reports look like this:

    byte   0        1         2           3 .. 31
           command  channel   value_id    value_data, padded with zeros
           <-------- header ---------->   <-------- data -------->

Other commands reuse the same 32 bytes differently: `0x12` and `0x13` put a
16-bit offset in bytes 1 and 2 and the length in byte 3, and `0x0B` uses byte 1
for Framework's factory command.

Two programs writing at the same time cannot tell their replies apart, and a
reply to an earlier question can be read as the answer to a later one. The
host-side tool that drives this holds a lock and drains stale reports before
every write. If you write your own tool, do the same.

The command ids used here, from `quantum/via.h`:

| id | value | meaning |
|---|---|---|
| `id_custom_set_value` | `0x07` | write a custom value |
| `id_custom_get_value` | `0x08` | read a custom value |
| `id_custom_save` | `0x09` | persist custom values |
| `id_bootloader_jump` | `0x0B` | jump to the bootloader, intercepted by Framework, see [FLASHING.md](FLASHING.md) |
| `id_dynamic_keymap_get_buffer` | `0x12` | read the EEPROM keymap |
| `id_dynamic_keymap_set_buffer` | `0x13` | write the EEPROM keymap |
| `id_unhandled` | `0xFF` | the answer when the firmware does not know what was asked |

Command ids `0x07` to `0x09` go to `via_custom_value_command()`, which dispatches
on the channel. QMK handles channel 1 (backlight, which this board enables) and
channel 3 (RGB matrix). Channels 0, 2, 4 and 5 fall through to
`via_custom_value_command_kb()`, which is the function this firmware adds, and
which handles channel 0 only; this board enables no rgblight, audio or LED
matrix, so the other three reach that handler and are rejected there. Channel 0
is the keyboard-specific channel in VIA's numbering, and that is where the
palette lives.

## Per-key colour: channel 0

`value_id` is the cell number. `value_data` is three bytes, red, green, blue,
0 to 255.

| command | request | reply |
|---|---|---|
| set a cell | `07 00 <cell> <r> <g> <b>` | same bytes |
| get a cell | `08 00 <cell>` | `08 00 <cell> <r> <g> <b>` |
| save | `09 00 <cell>` | same bytes, nothing happens |

The "save" command is accepted and does nothing. The palette belongs to the host:
if the keypad kept a copy in EEPROM and the host changed its table while the
module was unplugged, the keypad would show colours the panel no longer uses.

Anything the firmware does not handle comes back with `command_id` set to
`0xFF`, so a host can tell "this firmware does not have the palette" from "this
cell did not answer". The flasher prints the first as "not implemented by this
firmware" and the second as `None`, which are different things.

### Which cell is which key

Cells are numbered row-major over the keypad, four columns, starting one row
below the top row:

    cell = (keypad row - 1) * 4 + keypad column

| cell | panel position | keypad row, col | LED index |
|---|---|---|---|
| 0 | 0,0 | 1,0 | 4 |
| 1 | 0,1 | 1,1 | 0 |
| 2 | 0,2 | 1,2 | 20 |
| 3 | 0,3 | 1,3 | 18 |
| 4 | 1,0 | 2,0 | 7 |
| 5 | 1,1 | 2,1 | 1 |
| 6 | 1,2 | 2,2 | 21 |
| 7 | 1,3 | 2,3 | 16 |
| 8 | 2,0 | 3,0 | 6 |
| 9 | 2,1 | 3,1 | 3 |
| 10 | 2,2 | 3,2 | 23 |
| 11 | 2,3 | 3,3 | 19 |
| 12 | 3,0 | 4,0 | 9 |
| 13 | 3,1 | 4,1 | 11 |
| 14 | 3,2 | 4,2 | 15 |
| 15 | not drawn | 4,3 | 13, unused by the panel |

The panel's grid is 4 by 4 and the keypad has 24 keys, so 15 of them are panel
keys. The sixteenth cell of the grid falls on a key that exists (LED index 13)
but that the panel does not map. Writing to cell 15 is accepted and stored, and
the panel never uses it: the paint pass skips the cell, so the key keeps the dim
layer colour like the other non-panel keys.

The remaining nine keys are not panel keys: the four layer keys in the top row,
the four keys in the bottom row, and the one key at row 4, column 3. They are
painted at low brightness in the active layer's colour, so they read as "not a
panel key" whatever the hue.

The cell table comes from `g_led_config` in Framework's
`macropad.c`, which maps matrix positions to LED indices, and from the physical
positions of those LEDs. Writing the firmware from a drawing of the keypad would
have been wrong: the LED wiring order is deliberately not the visual order, which
is why `macropad.c` carries the comment about re-arranging the driver map.

## The layer colour: channel 3

The same raw HID interface carries QMK's own RGB matrix channel, which the
shipped firmware does implement. Its value ids are 1 brightness, 2 effect,
3 effect speed, 4 colour.

| command | request | reply |
|---|---|---|
| read the layer colour | `08 03 04` | `08 03 04 <hue> <saturation>` |

The firmware sets that colour on every layer change with
`rgb_matrix_sethsv_noeeprom()`, so the value is whatever the last layer change
set: full saturation, full value, and one of four hues.

The four layer keys in the keymap this was built for are called tc0 to tc3.

| layer | key | hue | saturation |
|---|---|---|---|
| 0 | tc0 | 128 | 255 |
| 1 | tc1 | 85 | 255 |
| 2 | tc2 | 42 | 255 |
| 3 | tc3 | 0 | 255 |

The panel reads this hue to know which layer is in force. It is an indirect
signal.

There is one caveat at boot. The RGB matrix loads its saved colour from EEPROM
during init, after the layer hooks have run, so until the first layer change
channel 3 reports the stored colour rather than the layer's. Ask the diagnostics
if you need the layer in that window.

## Diagnostics: 0xF0 and 0xF1

Two read-only value ids on channel 0 answer with three bytes:

| `value_id` | byte 3 | byte 4 | byte 5 |
|---|---|---|---|
| `0xF0` | active layer | layer changes since boot | `layer_state` low byte |
| `0xF1` | active layer | layer changes since boot | `default_layer_state` low byte |

"Active layer" is the highest layer in force, asking both `layer_state` and
`default_layer_state`, because a keymap can move either one. "Changes since
boot" increments in both layer hooks and wraps at 255, and both value ids report
the same counter, so they will always show the same number.

These exist because a colour that did not change is ambiguous: the keypad might
not have changed layer, or the firmware might not have noticed. With the
diagnostics, the host can tell the two apart. I added them after losing an
evening to exactly that ambiguity.

A get on `0xF0` or `0xF1` with any other command id is answered with
`id_unhandled`, because they are read-only.

## EEPROM keymap: 0x12 and 0x13

Not part of the palette, but used by the flasher before and after every flash.

| command | request | reply |
|---|---|---|
| read | `12 <offset hi> <offset lo> <length>` | `12 <hi> <lo> <length> <data...>` |
| write | `13 <offset hi> <offset lo> <length> <data...>` | echo |

The keymap is 640 bytes: 10 layers, 4 matrix rows, 8 columns, 2 bytes per keycode,
big-endian. It is read and written in chunks of 28 bytes, which is what fits in a
32-byte report after the four header bytes.

## A worked exchange

Set cell 0 to red, then read it back and ask which layer is in force. Values in
hex; every report is padded to 32 bytes with zeros, and only the bytes that
carry something are shown:

    host ->  07 00 00 ff 00 00
    keypad    07 00 00 ff 00 00        (echo)
    host ->  08 00 00
    keypad    08 00 00 ff 00 00
    host ->  08 03 04
    keypad    08 03 04 80 ff           (layer 0: hue 128, sat 255)
    host ->  08 00 f0
    keypad    08 00 f0 00 04 01        (layer 0, 4 changes, state 1)

## Driving it from Python

The whole protocol is short enough to write out. This is the same idea the
flasher uses, condensed and without the keymap commands or the error handling:

    import glob, os, select, time

    def node():
        # the module has several HID interfaces; VIA's raw HID is the one on
        # interface 1.1 on this host, which is what the flasher matches on too
        for n in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
            real = os.path.realpath(n)
            if '32AC:0013' in real.upper() and ':1.1/' in real:
                return '/dev/' + os.path.basename(n)

    class Via:
        def __init__(self, path):
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            os.close(self.fd)

        def _drain(self):
            while select.select([self.fd], [], [], 0)[0]:
                os.read(self.fd, 32)

        def ask(self, payload, timeout=0.5):
            self._drain()
            os.write(self.fd, bytes(payload) + bytes(32 - len(payload)))
            deadline = time.time() + timeout
            while time.time() < deadline:
                ready = select.select([self.fd], [], [], deadline - time.time())[0]
                if not ready:
                    break
                reply = list(os.read(self.fd, 32))
                if reply[0] in (payload[0], 0xFF) and reply[1:3] == list(payload[1:3]):
                    return reply

        def set_cell(self, cell, rgb):
            self.ask([0x07, 0x00, cell, *rgb])

        def get_cell(self, cell):
            reply = self.ask([0x08, 0x00, cell])
            return reply[3:6] if reply else None

        def layer_colour(self):
            reply = self.ask([0x08, 0x03, 0x04])
            return (reply[3], reply[4]) if reply else None

    with Via(node()) as v:        # the real script passes a path in
        v.set_cell(0, (255, 0, 0))
        print(v.get_cell(0), v.layer_colour())

`ask()` drains stale replies, writes the request padded to 32 bytes, accepts a
reply whose command is either the request's or `0xFF` and whose channel and value
id match, and gives up after a timeout. A reply that was already waiting is read
as the answer to the new question, which is why the drain comes first. A firmware
that does not implement the channel answers `0xFF`, and silence returns `None`.
The flasher keeps those two apart in its status output; the condensed client
above would turn both into zeros.

The no-reply ambiguity is also pinned mechanically, in
[`tests/test_flash_macropad.py`](../tests/test_flash_macropad.py), which runs
`ask()` over a socket pair and needs no hardware.

[`flash-macropad.py`](../flash-macropad.py) has the retries and the keymap dump.

## Finding the interface

The raw HID interface is not always the first hidraw node the module exposes. On
this host it is the one whose sysfs path contains `:1.1/`, and VIA's usage page
is `0xFF60`. List what is there before guessing:

    for n in /sys/class/hidraw/hidraw*; do
        echo "$n $(readlink -f "$n")"
    done | grep -i 32ac

The path shows the USB interface, and `udevadm info -q property -n /dev/hidrawN`
shows the attributes udev matched on.

## Porting it to another keyboard

Find where VIA's raw HID arrives: `raw_hid_receive`
in QMK, through `via_command_kb` if the keyboard defines one. Probe channel 0 on
the stock firmware, because if every request answers `id_unhandled` the channel is
free. Add `via_custom_value_command_kb` for your own value ids, and a paint
callback that runs after the effect if you want per-key colour. Then decide what a
cell means for your keypad, because that vocabulary is the only thing the host
and the firmware share.

## Things to try on the module

* Write cell 15 and read it back. The value is stored and nothing on the keypad
  changes. Write cell 16: the answer is `id_unhandled`.
* Set cell 0 to red and replug the module. Cell 0 is back to the firmware's
  default palette, because the palette lives in RAM and nothing keeps a copy; a
  host that is still running pushes its own table again when the module returns.
* Ask a stock module for a cell (`08 00 00`): it answers `id_unhandled`, while
  `08 03 04` still answers, because channel 3 is in the shipped firmware.
* Change one byte of `firmware-panel-palette.uf2` and run the tests: the sha256
  test fails before anything is flashed.
* Put a second RP2040 board in its bootloader, then run the flasher. It prints
  the volume it ignored and waits for a new one.
