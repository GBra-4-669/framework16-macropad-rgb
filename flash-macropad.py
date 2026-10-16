#!/usr/bin/env python3
"""Flash the Framework Laptop 16 RGB Macropad with a firmware built from
FrameworkComputer/qmk_firmware (branch fl16-2025).

Run as your user, not root: hidraw access comes from the udev rule in udev/, and
only the mount and the copy need sudo.

    python3 flash-macropad.py [firmware.uf2]     flash, then restore the keymap
    python3 flash-macropad.py --status           print state, change nothing

The steps, in order: save the EEPROM keymap, ask before writing anything, send
Framework's bootloader command over the VIA raw HID interface, find the RPI-RP2
volume, copy the image and verify it by sha256, wait for the module to come back,
restore the keymap, print the state. --yes skips the question. BUILD-NOTES.md
explains why each step is there.
"""

import argparse
import glob
import json
import os
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")

DEFAULT_FIRMWARE = os.path.join(HERE, "firmware-panel-palette.uf2")
DEFAULT_BACKUP_DIR = os.path.join(HOME, ".local", "state", "f16-macropad")
DECK_STATE = os.path.join(HOME, ".local", "bin", "deck-state")
MOUNT_POINT = "/tmp/rp2boot"

MACROPAD_USB_ID = "32AC:0013"  # hidraw node to open
BOOTLOADER_LABEL = "RPI-RP2"   # label on the bootloader's partition

# The dynamic keymap is 10 layers x 4 rows x 8 cols x 2 bytes. VIA's buffer
# commands are happiest with 28-byte reports.
KEYMAP_SIZE = 640
CHUNK = 28

# VIA command ids used here, and the layer colour on VIA's rgb channel.
CMD_CUSTOM_SET = 0x07
CMD_CUSTOM_GET = 0x08
CMD_KEYMAP_GET_BUFFER = 0x12
CMD_KEYMAP_SET_BUFFER = 0x13
RGB_CHANNEL = 3
RGB_VALUE_COLOR = 4

# Framework intercepts VIA's bootloader command (0x0B) and reads the next byte as
# one of their own factory commands; f_bootloader is 0xFE.
FACTORY_BOOTLOADER = [0x0B, 0xFE]


def log(msg):
    print(msg, flush=True)


def via_device():
    """The macropad's hidraw node, matched on USB id and interface."""
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        real = os.path.realpath(node)
        if MACROPAD_USB_ID in real.upper() and ":1.1/" in real:
            return "/dev/" + os.path.basename(node)
    return None


class Via:
    def __init__(self, dev):
        self.fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _drain(self):
        while True:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if not ready:
                return
            try:
                if not os.read(self.fd, 32):
                    return
            except BlockingIOError:
                return

    def ask(self, payload, timeout=0.5):
        """Send one 32-byte report and wait for a reply with the same header.

        VIA's raw HID has no request id, so the header bytes are all there is to
        match on; a stale reply from another writer would look the same, which is
        why the host-side tool holds a lock.
        """
        self._drain()
        os.write(self.fd, bytes(payload) + bytes(32 - len(payload)))
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready, _, _ = select.select([self.fd], [], [], max(0, deadline - time.time()))
            if not ready:
                break
            try:
                reply = list(os.read(self.fd, 32))
            except BlockingIOError:
                continue
            if len(reply) >= 3 and reply[0] == payload[0] and reply[1] == payload[1] and reply[2] == payload[2]:
                return reply
        return None

    def dump_keymap(self):
        data = bytearray()
        for off in range(0, KEYMAP_SIZE, CHUNK):
            n = min(CHUNK, KEYMAP_SIZE - off)
            r = self.ask([CMD_KEYMAP_GET_BUFFER, (off >> 8) & 0xFF, off & 0xFF, n])
            if not r or len(r) < 4 + n:
                raise RuntimeError(f"keymap read failed at offset {off}")
            data += bytes(r[4:4 + n])
        return bytes(data)

    def restore_keymap(self, data):
        for off in range(0, len(data), CHUNK):
            chunk = data[off:off + CHUNK]
            r = self.ask([CMD_KEYMAP_SET_BUFFER, (off >> 8) & 0xFF, off & 0xFF, len(chunk)] + list(chunk))
            if not r:
                raise RuntimeError(f"keymap write failed at offset {off}")
            time.sleep(0.05)
        return self.dump_keymap() == data

    def layer_colour(self):
        """The module's active layer, as the RGB colour it reports on VIA's rgb channel."""
        r = self.ask([CMD_CUSTOM_GET, RGB_CHANNEL, RGB_VALUE_COLOR])
        return (r[3], r[4]) if r else None

    def diagnostics(self, value_id):
        """0xF0: active layer, layer changes since boot, layer_state low byte. 0xF1: same for the default layer."""
        r = self.ask([CMD_CUSTOM_GET, 0, value_id])
        return (r[3], r[4], r[5]) if r else None

    def cell_colour(self, cell):
        r = self.ask([CMD_CUSTOM_GET, 0, cell])
        return tuple(r[3:6]) if r else None

    def reboot_to_bootloader(self):
        os.write(self.fd, bytes(FACTORY_BOOTLOADER) + bytes(30))


def wait_for_bootloader(seconds=30):
    """The bootloader's partition, found by its label.

    It shows up as /dev/sda1 (label RPI-RP2), not as a bare disk, so the whole-disk
    node is not the one to mount. If this machine has no /dev/sd* nodes at all, find
    it with `lsblk -o NAME,LABEL` and mount it by hand.
    """
    for _ in range(seconds):
        for node in sorted(glob.glob("/sys/block/sd*")):
            name = os.path.basename(node)
            part = f"{name}1" if os.path.exists(f"/sys/block/{name}/{name}1") else name
            label = subprocess.run(["lsblk", "-o", "LABEL", "-n", f"/dev/{part}"],
                                   capture_output=True, text=True).stdout.strip()
            if label == BOOTLOADER_LABEL:
                return f"/dev/{part}"
        time.sleep(1)
    return None


def wait_for_keyboard(seconds=30):
    for _ in range(seconds):
        dev = via_device()
        if dev:
            return dev
        time.sleep(1)
    return None


def retrigger_udev():
    subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], capture_output=True)
    subprocess.run(["sudo", "udevadm", "trigger", "--action=add",
                    "--subsystem-match=hidraw", "--attr-match=idVendor=32ac"],
                   capture_output=True)


def open_via(dev, attempts=10):
    """Open the module, waiting for the udev ACL after a re-enumeration.

    Access has to be waited for, not assumed: opening too early used to crash this
    script after the flash but before the keymap was put back.
    """
    for attempt in range(attempts):
        try:
            return Via(dev)
        except PermissionError:
            log(f"  {dev} not readable yet (attempt {attempt + 1}) - re-triggering udev")
            retrigger_udev()
            time.sleep(2)
    return None


def confirm_flash(fw):
    log("")
    log("About to put the macropad into its bootloader and write:")
    log(f"  {fw}")
    log("Its EEPROM keymap is backed up above and will be restored afterwards.")
    log("Framework's stock images and erase_flash.uf2 can be flashed back at any time.")
    try:
        answer = input("Type 'flash' to continue: ").strip().lower()
    except EOFError:
        answer = ""
    return answer == "flash"


def print_status(v):
    log(f"layer colour (hue, sat): {v.layer_colour()}")
    log(f"layer/changes/state: {v.diagnostics(0xF0)}")
    log(f"default layer/changes/state: {v.diagnostics(0xF1)}")
    log(f"cell 0: {v.cell_colour(0)}")


def flash(fw, backup_dir, use_deck, assume_yes):
    dev = via_device()
    if not dev:
        log("macropad not found - is it plugged in?")
        return 1
    log(f"macropad at {dev}")

    # 1. back up the keymap: the flash resets EEPROM to the compiled keymap
    v = open_via(dev)
    if v is None:
        return 1
    with v:
        keymap = v.dump_keymap()
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, "keymap-" + time.strftime("%Y%m%d-%H%M%S") + ".hex")
        with open(backup, "w") as fh:
            fh.write(keymap.hex())
        log(f"keymap backed up: {len(keymap)} bytes -> {backup}")

        if not assume_yes and not confirm_flash(fw):
            log("not flashing")
            return 1

        # 2. jump to the bootloader
        log("sending Framework's bootloader command [0x0B, 0xFE] ...")
        try:
            v.reboot_to_bootloader()
        except OSError as e:
            log(f"  write failed: {e}")
        try:
            v.close()
        except OSError:
            pass

    # 3. find the volume, copy the firmware onto it, verify the copy
    volume = wait_for_bootloader()
    if not volume:
        log("no RPI-RP2 volume appeared - the jump did not take")
        return 1
    log(f"bootloader volume: {volume}")
    os.makedirs(MOUNT_POINT, exist_ok=True)
    if subprocess.run(["sudo", "mount", volume, MOUNT_POINT]).returncode != 0:
        log("mount failed")
        return 1
    subprocess.run(["sudo", "cp", fw, MOUNT_POINT + "/"], check=True)
    subprocess.run(["sudo", "sync"])
    src = subprocess.run(["sha256sum", fw], capture_output=True, text=True).stdout.split()[0]
    dst = subprocess.run(["sudo", "sha256sum", f"{MOUNT_POINT}/{os.path.basename(fw)}"],
                         capture_output=True, text=True).stdout.split()[0]
    if src != dst:
        log("copied image does not match the source - not trusting it")
        subprocess.run(["sudo", "umount", MOUNT_POINT], capture_output=True)
        return 1
    log("copied and verified")

    # 4. wait for the module to reboot, then write the keymap back
    for _ in range(30):
        time.sleep(1)
        if not os.path.exists(volume):
            break
    subprocess.run(["sudo", "umount", MOUNT_POINT], capture_output=True)
    dev = wait_for_keyboard()
    if not dev:
        log("the module did not come back as a keyboard")
        log(f"restore the keymap by hand from {backup} once it does")
        return 1
    log(f"macropad back at {dev}")

    v = open_via(dev)
    if v is None:
        log(f"cannot open {dev} - restore the keymap by hand from {backup}")
        return 1
    with v:
        log("restoring the keymap ...")
        if v.restore_keymap(keymap):
            log("  keymap restored and verified")
        else:
            log(f"  KEYMAP RESTORE FAILED - restore by hand from {backup}")
        print_status(v)

    # 5. optional: report what the host-side tool makes of it
    if use_deck and os.path.exists(DECK_STATE):
        try:
            state = subprocess.run([DECK_STATE], capture_output=True, text=True).stdout
            d = json.loads(state)
            log(f"deck-state: gate={d['gate']} layer={d['macropad']['layer']} ({d['reason']})")
        except (OSError, ValueError, KeyError) as e:
            log(f"deck-state: could not read its state ({e})")
    return 0


def main():
    p = argparse.ArgumentParser(
        description="Flash the Framework Laptop 16 RGB Macropad and restore its keymap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See BUILD-NOTES.md for why each step exists.")
    p.add_argument("firmware", nargs="?", default=DEFAULT_FIRMWARE,
                   help="UF2 image to flash (default: firmware-panel-palette.uf2)")
    p.add_argument("--status", action="store_true",
                   help="print layer colour and diagnostics, change nothing")
    p.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR,
                   help=f"where to save the EEPROM keymap (default: {DEFAULT_BACKUP_DIR})")
    p.add_argument("--no-deck", action="store_true",
                   help="do not call the host-side deck-state tool at the end")
    p.add_argument("--yes", action="store_true",
                   help="do not ask before writing to the module")
    args = p.parse_args()

    dev = via_device()
    if not dev:
        log("macropad not found - is it plugged in?")
        return 1

    if args.status:
        log(f"macropad at {dev}")
        v = open_via(dev)
        if v is None:
            log("cannot open the module - is the udev rule in udev/ installed?")
            return 1
        with v:
            print_status(v)
        return 0

    if not os.path.exists(args.firmware):
        log(f"firmware not found: {args.firmware}")
        return 1
    return flash(args.firmware, args.backup_dir, not args.no_deck, args.yes)


if __name__ == "__main__":
    sys.exit(main())
