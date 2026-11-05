# Flashing

> **Read this before you run it.** Flashing replaces the firmware on the
> macropad. It is recoverable: Framework publishes stock images, and the module
> enters an RP2040 bootloader that shows up as a USB drive. A new build resets
> the EEPROM keymap on first boot, because QMK's stored-keymap validity comes
> from the build date. Reflashing the same image does not. Back the keymap up
> first; the script in this repo does that automatically and puts it back
> afterwards. The mount, the copy,
> the sync, the comparison, the unmount and the udev retrigger use `sudo`;
> opening the module does not. Read the script before running it, and check the
> volume yourself with `lsblk -o NAME,LABEL` if you want to see what it writes
> to.

This is a worked example from one module, not supported firmware and not a
Framework release. If it breaks, the way back is below.

## What the bootloader is

The module's RP2040 has a bootloader in ROM. When it runs, the module stops being
a keyboard and becomes a USB mass storage device with the label `RPI-RP2`, and
the `.uf2` is copied onto it like a file. No programmer and no `dfu-util`.

On the machine this was written on, the bootloader appeared as a partition of a
new disk, not as the disk itself: mounting the whole-disk node failed, and the
partition mounted. That detail depends on the host, so do not assume a device
node. Match the label:

    lsblk -o NAME,LABEL,SIZE

The script does this with `lsblk --json` and works from the label.

## Getting into the bootloader

Normally VIA sends command `0x0B` (bootloader jump) over raw HID and QMK jumps.
Framework's `keyboards/framework/factory.c` takes that command id over and reads
the **next** byte as one of their own factory commands:

    [0x0B, 0xFE]      f_bootloader

Plain `[0x0B]` does nothing. Their code logs `Unknown factory command: 0` and
returns before QMK ever sees the request.

`QK_BOOT` written into the EEPROM keymap did nothing either. I tried it on
layers 1 to 3, twice, and the module stayed a keyboard.

There is a second documented way in, but it belongs to different firmware.
Framework's [board page for these modules](https://docs.zephyrproject.org/latest/boards/framework/laptop16_keyboard/doc/index.html)
says to remove the module and hold both Alt keys (or 1 and 6 on the numpad)
while powering it up. That page documents Framework's Zephyr firmware, which is
not what this module runs: the macropad's `info.json` has `"bootmagic": false`,
and the QMK keyboard code has no key check at power-up either.

If the firmware will not run at all, the RP2040 bootloader has to be forced in
hardware. Framework's knowledge base article
[Keyboard Firmware Update (Framework Laptop 16)](https://knowledgebase.frame.work/en_us/keyboard-firmware-update-framework-laptop-16-r1LayV4Age)
covers their module. I have not needed that route, so I am not going to describe
it from memory.

## The way back

Two independent ways back, both from Framework:

* the stock firmware, published as `framework_macropad_default_v0.3.1.uf2` on the
  [v0.3.1 release](https://github.com/FrameworkComputer/qmk_firmware/releases/tag/v0.3.1)
  of their QMK fork, alongside the other input module variants;
* `erase_flash.uf2` on the same release. It is the generic erase image for their
  RP2040 boards, not a macropad-specific file. Read their instructions before
  using it.

Neither is included in this repository. Download one before you need it, not
after.

## Before the first flash

1. **Back up the keymap.** A rebuilt image resets the EEPROM keymap on first
   boot. The script dumps it before it touches the module, so running the script
   is the backup. If you are doing this by hand, do the dump first (see below).
2. **Install the udev rule.** Without it the hidraw node belongs to root and the
   script cannot open the module as your user. See [udev](#udev).
3. **Know the recovery image.** See above.

## The flasher

Run it as your user, not with `sudo`; the warning above says what escalates.

    python3 flash-macropad.py                    # flash firmware-panel-palette.uf2
    python3 flash-macropad.py other.uf2          # flash a different image
    python3 flash-macropad.py --status           # print state, change nothing
    python3 flash-macropad.py --dump backup.hex  # save the EEPROM keymap
    python3 flash-macropad.py --restore backup.hex  # put a keymap back

| Option | Default | What it does |
|---|---|---|
| `firmware` | `firmware-panel-palette.uf2` next to the script | image to flash |
| `--status` | | print layer colour, diagnostics and cell 0, change nothing |
| `--dump FILE` | | write the EEPROM keymap to `FILE` as hex, change nothing |
| `--restore FILE` | | write a keymap from `FILE` back to the module and verify it |
| `--backup-dir DIR` | `keymap-backups/` next to the script | where the automatic backup goes |
| `--mount-point DIR` | a temporary directory | where the bootloader volume is mounted |
| `--hidraw DEV` | auto | use a specific hidraw node instead of matching USB id |
| `--host-command CMD` | none | optional: run this command after the flash and print its output |
| `--expect-sha256 HEX` | the `.sha256` file next to the image | refuse to flash unless the image matches |
| `--yes` | | skip the confirmation prompt |

The steps, in order:

1. check every block of the image and its sha256, before the module is touched;
2. find the module's hidraw node by USB id (`32ac:0013`, VIA raw HID interface);
3. dump the 640-byte EEPROM keymap and write it to `--backup-dir`;
4. ask, unless `--yes`;
5. send `[0x0B, 0xFE]` and wait for a `RPI-RP2` volume that was not there before
   the jump;
6. mount it, copy the image, `sync`, compare sha256 of source and destination,
   unmount;
7. wait for the module to come back as a keyboard;
8. write the keymap back and read it out again to check it;
9. print the state, and optionally the output of `--host-command`.

A run looks like this:

    $ python3 flash-macropad.py
    image: /path/to/framework16-macropad-rgb/firmware-panel-palette.uf2 (113664 bytes, sha256 verified)
    macropad at /dev/hidraw9
    keymap backed up: 640 bytes -> /path/to/framework16-macropad-rgb/keymap-backups/keymap-20260916-143102.hex
    About to put the macropad into its bootloader and write:
      /path/to/framework16-macropad-rgb/firmware-panel-palette.uf2
    Its EEPROM keymap is backed up above and will be restored afterwards.
    Framework's stock images and erase_flash.uf2 can be flashed back at any time.
    Type 'flash' to continue: flash
    sending Framework's bootloader command [0x0B, 0xFE] ...
    bootloader volume: /dev/sda1
    copied and verified
    macropad back at /dev/hidraw9
    restoring the keymap ...
      keymap restored and verified
    layer colour (hue, sat): (128, 255)
    layer/changes/state: (0, 4, 1)
    default layer/changes/state: (0, 4, 1)
    cell 0: (255, 0, 0)

Nothing is written until the UF2 block check and the sha256 pin pass: a wrong
file, a bad length or a modified image is refused there. The comparison after
the copy is a report, not a gate. It cannot stop the module booting, because the
RP2040 bootloader reboots as soon as the last block is written. A short copy
never reaches the last block, so the bootloader stays there and the mismatch
leaves the module in it. A complete but corrupt copy has already rebooted by the
time the comparison runs, and that is what the recovery image is for.

## Doing it by hand

Everything the script does can be done in a shell, and if it fails this is how
to find out where.

Dump the keymap first, while the module still works:

    python3 flash-macropad.py --dump before.hex

Send the bootloader jump. `os.write` on the hidraw node is the whole protocol
here, so a few lines are enough; match the node by USB id rather than by number:

    python3 - <<'PY'
    import glob, os
    for node in glob.glob('/sys/class/hidraw/hidraw*'):
        real = os.path.realpath(node)
        if '32AC:0013' in real.upper() and ':1.1/' in real:
            fd = os.open('/dev/' + os.path.basename(node), os.O_RDWR)
            os.write(fd, bytes([0x0B, 0xFE]) + bytes(30))
            os.close(fd)
            break
    PY

Then find the volume and copy:

    lsblk -o NAME,LABEL,SIZE
    sudo mount /dev/sda1 /mnt          # use the node with LABEL=RPI-RP2
    sudo cp firmware-panel-palette.uf2 /mnt/
    sudo sync
    sudo umount /mnt

The module reboots into the new firmware in about a second. Then put the keymap
back, or it will be running the compiled default:

    python3 flash-macropad.py --restore before.hex

## The keymap problem

The dynamic keymap lives in the module's EEPROM, not in the image. After the
first flash the module came back running the compiled `default` keymap: 72 of the
320 keycodes had changed.

The keymap is 640 bytes: 10 layers, 4 matrix rows, 8 columns, 2 bytes per keycode,
big-endian. Dumping and restoring uses VIA's buffer commands, 28 bytes at a time,
23 chunks, and the restore was verified by reading the whole thing back. The
script does that automatically; by hand, `--dump` and `--restore` are the same
code.

The cause is the build date. QMK keeps a magic in EEPROM derived from
`QMK_BUILDDATE`, and when it does not match, `via_eeprom_is_valid()` fails and
`eeconfig_init_via()` copies the compiled keymap over the stored one
(`quantum/via.c`). A different build has a different date, so the first boot
after a rebuild starts from the compiled keymap. Reflashing the same image keeps
the magic valid and leaves the stored keymap alone, because the emulated EEPROM
sits above the image in the same flash. That is why the script dumps before and
restores after.

There is a consequence if you flash by hand and do not restore a keymap. The
compiled keymap in this patch is Framework's layout with its layer hooks
removed, and the layer keys live in the EEPROM keymap, so after a flash without
a restore the module is a numpad on layer 0 with no route to layers 1 and 2,
where the RGB and backlight controls are. The flasher puts your keymap back; a
hand flash does not, so do the `--restore` at the end.

## udev

The module exposes its raw HID interface as a hidraw node, and by default that
node is `root:root 0600`. The rule in `udev/` gives it to the `input` group and
adds the systemd `uaccess` tag:

    sudo cp udev/99-framework-macropad-via.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules
    sudo udevadm trigger

On the machine this was written on, the `uaccess` ACL did not come back after the
module re-enumerated following a flash. The node was `root:root 0600` even though
the udev database showed the tag, and only root could open it. The panel stays
shut, which sends you looking in the wrong place.

The rule has a second grant for that case: `GROUP="input"`, which makes the node
readable without the ACL. That group can read every input device, not only this
one, so the grant is a trade. If you would rather not have it, delete the
`GROUP="input"` part and rely on `uaccess`, and if the node comes back
unreadable, `sudo udevadm trigger --action=add --subsystem-match=hidraw` and
replug. If you do want it, the membership is `sudo usermod -aG input $USER`,
followed by a new login session. The script tries the trigger and waits before it
gives up on opening the module.

## When it does not work

| What you see | Likely cause | What to do |
|---|---|---|
| `macropad not found` | module not connected, or a different USB id | `lsusb` for `32ac:0013`; pass `--hidraw` if you know the node |
| `no new RPI-RP2 volume appeared` | the jump did not take, or the only volumes present were already there | retry; watch `dmesg -w`, and unplug other boards the script listed |
| `mount failed` | the desktop auto-mounted the volume, the mount point is busy, or sudo failed | check `mount`, unmount the volume, mount the node `lsblk` labels `RPI-RP2` yourself |
| `cannot open the module` after a flash | udev ACL gone | install the rule, or `sudo udevadm trigger` |
| module works, palette does not | host tool not running, or wrong layer | `--status`, check the layer colour |
| keymap looks wrong after a flash | the restore did not run | `--restore` the backup from `keymap-backups/` |

### When the palette does not change

`--status` narrows this down before anything is touched:

| `--status` shows | The firmware thinks | Look at |
|---|---|---|
| layer changed, colour changed | everything works | the host program and its palette push |
| layer changed, colour stale | the layer moved, the write was overwritten | the boot-time colour and the brightness reset in the limits |
| layer did not change | the keymap did not move the layer, or a hook put it back | layer keys in the EEPROM keymap, the `led_update_user` trap |
| `not implemented by this firmware` | the module is not running this patch | flash the image |
| `None` | the module did not answer | udev permissions, or another process holding the interface |
