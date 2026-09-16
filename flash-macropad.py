#!/usr/bin/env python3
"""Flash the macropad with the firmware built in ~/qmk-framework.

Every step here was learned the hard way on 2026-09-16; see BUILD-NOTES.md in
that tree. In short:

  * the bootloader jump is a *Framework* factory command, not VIA's: command id
    0x0B with 0xFE as its first data byte, over the VIA raw HID interface;
  * the RP2040 bootloader presents a *partitioned* volume (/dev/sda1, "RPI-RP2"),
    so mounting the whole disk fails;
  * flashing resets the dynamic keymap, so it is dumped first and restored after;
  * the udev ACL for the module does not survive re-enumeration, so it is
    re-triggered afterwards and the module's readability is verified.

Run as the user (not root): the HID access comes from a udev ACL, and only the
mount and copy need sudo.
"""

import glob
import json
import os
import select
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
FIRMWARE = f"{HOME}/f16-macropad/firmware-panel-palette.uf2"
BACKUP = f"{HOME}/f16-macropad/keymap-before-flash.hex"
MNT = "/tmp/rp2boot"
DECK = f"{HOME}/.local/bin/deck-state"
KEYMAP_SIZE = 640          # 10 layers x 4 matrix rows x 8 cols x 2 bytes
CHUNK = 28                 # the report size VIA's buffer commands are happiest with


def log(msg):
    print(msg, flush=True)


def via_device():
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        real = os.path.realpath(node)
        if "32AC:0013" in real.upper() and ":1.1/" in real:
            return "/dev/" + os.path.basename(node)
    return None


class Via:
    def __init__(self, dev):
        self.fd = os.open(dev, os.O_RDWR | os.O_NONBLOCK)

    def close(self):
        os.close(self.fd)

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
            r = self.ask([0x12, (off >> 8) & 0xFF, off & 0xFF, n])
            if not r or len(r) < 4 + n:
                raise RuntimeError(f"keymap read failed at offset {off}")
            data += bytes(r[4:4 + n])
        return bytes(data)

    def restore_keymap(self, data):
        for off in range(0, len(data), CHUNK):
            chunk = data[off:off + CHUNK]
            r = self.ask([0x13, (off >> 8) & 0xFF, off & 0xFF, len(chunk)] + list(chunk))
            if not r:
                raise RuntimeError(f"keymap write failed at offset {off}")
            time.sleep(0.05)
        return self.dump_keymap() == data

    def layer_colour(self):
        r = self.ask([0x08, 3, 4])
        return (r[3], r[4]) if r else None


def wait_for_bootloader(seconds=30):
    for _ in range(seconds):
        for node in sorted(glob.glob("/sys/block/sd*")):
            name = os.path.basename(node)
            part = f"{name}1" if os.path.exists(f"/sys/block/{name}/{name}1") else name
            label = subprocess.run(["lsblk", "-o", "LABEL", "-n", f"/dev/{part}"],
                                   capture_output=True, text=True).stdout.strip()
            if label == "RPI-RP2":
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


def main():
    fw = sys.argv[1] if len(sys.argv) > 1 else FIRMWARE
    if not os.path.exists(fw):
        log(f"firmware not found: {fw}")
        return 1

    dev = via_device()
    if not dev:
        log("macropad not found - is it plugged in?")
        return 1

    log(f"macropad at {dev}")

    # 1. back up the keymap, because the flash will reset it
    v = Via(dev)
    keymap = v.dump_keymap()
    open(BACKUP, "w").write(keymap.hex())
    log(f"keymap backed up: {len(keymap)} bytes -> {BACKUP}")

    # 2. jump to the bootloader
    log("sending Framework's bootloader command [0x0B, 0xFE] ...")
    try:
        os.write(v.fd, bytes([0x0B, 0xFE]) + bytes(30))
    except OSError as e:
        log(f"  write failed: {e}")
    try:
        v.close()
    except OSError:
        pass

    # 3. find the volume and copy the firmware onto it
    volume = wait_for_bootloader()
    if not volume:
        log("no RPI-RP2 volume appeared - the jump did not take")
        return 1
    log(f"bootloader volume: {volume}")
    os.makedirs(MNT, exist_ok=True)
    if subprocess.run(["sudo", "mount", volume, MNT]).returncode != 0:
        log("mount failed")
        return 1
    subprocess.run(["sudo", "cp", fw, MNT + "/"], check=True)
    subprocess.run(["sudo", "sync"])
    src = subprocess.run(["sha256sum", fw], capture_output=True, text=True).stdout.split()[0]
    dst = subprocess.run(["sudo", "sha256sum", f"{MNT}/{os.path.basename(fw)}"],
                         capture_output=True, text=True).stdout.split()[0]
    log(f"copied and {'verified' if src == dst else 'MISMATCHED - do not trust it'}")
    if src != dst:
        return 1

    # 4. wait for it to reboot into the new firmware
    for _ in range(30):
        time.sleep(1)
        if not os.path.exists(volume):
            break
    subprocess.run(["sudo", "umount", MNT], capture_output=True)
    dev = wait_for_keyboard()
    if not dev:
        log("the module did not come back as a keyboard")
        return 1
    log(f"macropad back at {dev}")

    # 5. access has to be waited for, not assumed: after a re-enumeration the
    # node can come back root-only (uaccess did not apply on this machine until
    # the rule also granted a group), and opening it too early crashed this
    # script *after* the flash but *before* the keymap was put back.
    v = None
    for attempt in range(10):
        try:
            v = Via(dev)
            break
        except PermissionError:
            log(f"  {dev} not readable yet (attempt {attempt + 1}) - re-triggering udev")
            subprocess.run(["sudo", "udevadm", "control", "--reload-rules"], capture_output=True)
            subprocess.run(["sudo", "udevadm", "trigger", "--action=add",
                            "--subsystem-match=hidraw", "--attr-match=idVendor=32ac"],
                           capture_output=True)
            time.sleep(2)
    if v is None:
        log(f"cannot open {dev} - restore the keymap by hand from {BACKUP}")
        return 1

    # 6. put the keymap back and check the firmware answers
    log("restoring the keymap ...")
    if v.restore_keymap(keymap):
        log("  keymap restored and verified")
    else:
        log("  KEYMAP RESTORE FAILED - restore by hand from " + BACKUP)
    colour = v.layer_colour()
    log(f"layer colour now {colour} (tc0 should be (128, 255) with our firmware)")
    r = v.ask([0x08, 0, 0])
    log(f"per-key palette channel: cell 0 = {r[3:6] if r else 'no answer'}")
    v.close()

    state = subprocess.run([DECK], capture_output=True, text=True).stdout
    d = json.loads(state)
    log(f"deck-state: gate={d['gate']} layer={d['macropad']['layer']} ({d['reason']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
