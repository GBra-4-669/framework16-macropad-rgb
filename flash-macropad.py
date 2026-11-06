#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Flash the Framework Laptop 16 RGB Macropad with a firmware built from
FrameworkComputer/qmk_firmware (branch fl16-2025).

Run as your user, not root: hidraw access comes from the udev rule in udev/, and
the mount, the copy, the sync, the comparison, the unmount and the udev retrigger
use sudo.

    python3 flash-macropad.py                  flash, then put the keymap back
    python3 flash-macropad.py other.uf2        flash a different image
    python3 flash-macropad.py --status         print the state, change nothing
    python3 flash-macropad.py --dump out.hex   save the EEPROM keymap
    python3 flash-macropad.py --restore in.hex put a saved keymap back

Every path is an argument or relative to this file; nothing points into the
home directory. docs/FLASHING.md has the steps in order and why each one is
there.
"""

import argparse
import glob
import hashlib
import json
import os
import select
import shlex
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_FIRMWARE = os.path.join(HERE, "firmware-panel-palette.uf2")
DEFAULT_BACKUP_DIR = os.path.join(HERE, "keymap-backups")
UDEV_RULE = os.path.join(HERE, "udev", "99-framework-macropad-via.rules")

MACROPAD_USB_ID = "32AC:0013"  # hidraw node to open
BOOTLOADER_LABEL = "RPI-RP2"   # label on the bootloader's volume

# UF2 block fields, per the UF2 specification. Each block is 512 bytes, the first
# 32 are the header and the rest hold up to 476 bytes of payload.
UF2_BLOCK = 512
UF2_MAGIC = (0x0A324655, 0x9E5D5157)
UF2_FLAG_FAMILY_PRESENT = 0x00002000
UF2_FAMILY_RP2040 = 0xE48BFF56
UF2_FLASH_BASE = 0x10000000
UF2_FLASH_SIZE = 1 * 1024 * 1024  # the macropad's QSPI flash
UF2_MAX_PAYLOAD = 476

# The dynamic keymap is 10 layers x 4 rows x 8 cols x 2 bytes. VIA's buffer
# commands carry 28 bytes per report.
KEYMAP_SIZE = 640
CHUNK = 28

# VIA command ids used here, and the layer colour on VIA's rgb channel.
CMD_CUSTOM_SET = 0x07
CMD_CUSTOM_GET = 0x08
CMD_KEYMAP_GET_BUFFER = 0x12
CMD_KEYMAP_SET_BUFFER = 0x13
RGB_CHANNEL = 3
RGB_VALUE_COLOR = 4
ID_UNHANDLED = 0xFF

# Framework intercepts VIA's bootloader command (0x0B) and reads the next byte
# as one of their own factory commands; f_bootloader is 0xFE.
FACTORY_BOOTLOADER = [0x0B, 0xFE]

# Returned by the read helpers when the firmware answers id_unhandled, which is
# not the same thing as not answering at all.
UNHANDLED = object()


def log(msg):
    print(msg, flush=True)


def fail(msg):
    log(msg)
    return 1


def via_device(preferred=None):
    """The macropad's hidraw node, matched on USB id and VIA's raw HID interface.

    The module exposes more than one HID interface, and only the one on usage
    page 0xFF60 speaks VIA. Matching the interface path is what picks that one;
    if the numbering ever changes, --hidraw takes a node directly.
    """
    if preferred and os.path.exists(preferred):
        return preferred
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
        """Send one 32-byte report and wait for a reply to it.

        VIA's raw HID has no request id, so the header bytes are all there is to
        match on. A firmware that does not know the request answers with
        id_unhandled in byte 0 and leaves the channel and value bytes alone, so
        that is matched too; otherwise "not implemented" is indistinguishable
        from "no answer".
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
            if len(reply) < 3:
                continue
            same_question = reply[1] == payload[1] and reply[2] == payload[2]
            if (reply[0] == payload[0] or reply[0] == ID_UNHANDLED) and same_question:
                return reply
        return None

    def _get(self, channel, value_id):
        reply = self.ask([CMD_CUSTOM_GET, channel, value_id])
        if reply is None:
            return None
        if reply[0] == ID_UNHANDLED:
            return UNHANDLED
        return reply

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
        r = self._get(RGB_CHANNEL, RGB_VALUE_COLOR)
        if r is None or r is UNHANDLED:
            return r
        return (r[3], r[4])

    def diagnostics(self, value_id):
        """0xF0: active layer, layer changes since boot, layer_state low byte. 0xF1: same for the default layer."""
        r = self._get(0, value_id)
        if r is None or r is UNHANDLED:
            return r
        return (r[3], r[4], r[5])

    def cell_colour(self, cell):
        r = self._get(0, cell)
        if r is None or r is UNHANDLED:
            return r
        return tuple(r[3:6])

    def reboot_to_bootloader(self):
        os.write(self.fd, bytes(FACTORY_BOOTLOADER) + bytes(30))


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sudo_run(argv):
    """Prefer passwordless sudo, fall back to one interactive prompt."""
    result = subprocess.run(["sudo", "-n"] + argv, capture_output=True, text=True)
    if result.returncode == 0:
        return result
    return subprocess.run(["sudo"] + argv, capture_output=True, text=True)


def sha256_with_sudo(path):
    result = sudo_run(["sha256sum", path])
    fields = result.stdout.split()
    return fields[0] if result.returncode == 0 and fields else None


def expected_sha256(path):
    """The checksum committed next to the image, or None if there is no sidecar."""
    sidecar = path + ".sha256"
    try:
        with open(sidecar) as fh:
            for line in fh:
                fields = line.split()
                if len(fields) >= 2 and fields[1].lstrip("*") == os.path.basename(path):
                    return fields[0].lower()
    except OSError:
        return None
    return None


def check_image(path):
    """Refuse to write something that is not a complete RP2040 UF2.

    Every block is checked, not just the first: a valid header followed by zeros,
    or by blocks that target somewhere else, would otherwise pass. A wrong or
    truncated file copied onto the bootloader volume is not obviously broken
    until the module fails to come back, so this happens before the module is
    touched. Returns the size, or None after logging why not.
    """
    if not os.path.isfile(path):
        log(f"{path} is not a regular file")
        return None
    try:
        size = os.path.getsize(path)
    except OSError as e:
        log(f"cannot read the image: {e}")
        return None
    if size == 0 or size % UF2_BLOCK:
        log(f"{path} is not a UF2: {size} bytes is not a whole number of {UF2_BLOCK}-byte blocks")
        return None
    blocks = size // UF2_BLOCK
    with open(path, "rb") as fh:
        for index in range(blocks):
            header = fh.read(32)
            fh.seek(UF2_BLOCK - 32, os.SEEK_CUR)
            try:
                magic0, magic1, flags, addr, payload, block_no, total, family = struct.unpack("<IIIIIIII", header)
            except struct.error:
                log(f"block {index}: short header")
                return None
            if (magic0, magic1) != UF2_MAGIC:
                log(f"block {index}: bad magic, this is not a UF2")
                return None
            if not flags & UF2_FLAG_FAMILY_PRESENT:
                log(f"block {index}: no family id, cannot tell what it is for")
                return None
            if family != UF2_FAMILY_RP2040:
                log(f"block {index}: not for an RP2040 (family {family:#010x})")
                return None
            if payload > UF2_MAX_PAYLOAD:
                log(f"block {index}: payload {payload} is larger than {UF2_MAX_PAYLOAD}")
                return None
            if block_no != index:
                log(f"block {index}: numbered {block_no}, not {index}; the file is out of order or has holes")
                return None
            if total != blocks:
                log(f"block {index}: file says {total} blocks but has {blocks}")
                return None
            if not (UF2_FLASH_BASE <= addr < UF2_FLASH_BASE + UF2_FLASH_SIZE):
                log(f"block {index}: target {addr:#010x} is outside the RP2040's flash")
                return None
    return size


def _walk_blockdevices(nodes):
    for node in nodes:
        yield node
        yield from _walk_blockdevices(node.get("children") or [])


def rp2_volumes():
    """Every block device currently labelled RPI-RP2, as name -> device node."""
    try:
        out = subprocess.run(["lsblk", "--json", "--output", "NAME,LABEL,TYPE"],
                             capture_output=True, text=True, check=True).stdout
        nodes = json.loads(out).get("blockdevices", [])
    except (OSError, subprocess.CalledProcessError, ValueError):
        return {}
    found = {}
    for node in _walk_blockdevices(nodes):
        if node.get("label") == BOOTLOADER_LABEL and node.get("type") in ("part", "disk"):
            found[node["name"]] = "/dev/" + node["name"]
    return found


def wait_for_bootloader(seconds=30, exclude=()):
    """A new bootloader volume, found by its label.

    On some hosts it appears as a partition of a new disk, on others as the disk
    itself, and the node names differ between SATA, NVMe and SD, so the label is
    the only reliable thing to match. Volumes that were already there before the
    jump are skipped: a Pico or another module left in its bootloader must not
    get this image written to it.
    """
    for _ in range(seconds):
        for name, node in rp2_volumes().items():
            if name not in exclude:
                return node
        time.sleep(1)
    return None


def wait_for_keyboard(seconds=30, preferred=None):
    for _ in range(seconds):
        dev = via_device(preferred)
        if dev:
            return dev
        time.sleep(1)
    return None


def retrigger_udev():
    """Re-apply hidraw permissions after a re-enumeration.

    Returns whether both commands succeeded. The trigger is not filtered on
    idVendor: that attribute lives on the parent USB device, not on the hidraw
    node.
    """
    rules = sudo_run(["udevadm", "control", "--reload-rules"])
    trigger = sudo_run(["udevadm", "trigger", "--action=add", "--subsystem-match=hidraw"])
    return rules.returncode == 0 and trigger.returncode == 0


def open_via(dev, attempts=15):
    """Open the module, waiting for the udev ACL after a re-enumeration.

    Access has to be waited for, not assumed: opening too early used to crash this
    script after the flash but before the keymap was put back. A missing node is
    also normal while the module is re-enumerating, so it is retried, not fatal.
    """
    udev_tries = 0
    for attempt in range(attempts):
        try:
            return Via(dev)
        except PermissionError:
            log(f"  {dev} not readable yet (attempt {attempt + 1})")
            if udev_tries < 2:
                udev_tries += 1
                retrigger_udev()
            time.sleep(2)
        except OSError:
            # ENOENT and ENODEV both mean "not back yet" during a reboot.
            time.sleep(1)
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


def describe(value):
    return "not implemented by this firmware" if value is UNHANDLED else value


def print_status(v):
    log(f"layer colour (hue, sat): {describe(v.layer_colour())}")
    log(f"layer/changes/state: {describe(v.diagnostics(0xF0))}")
    log(f"default layer/changes/state: {describe(v.diagnostics(0xF1))}")
    log(f"cell 0: {describe(v.cell_colour(0))}")


def mount_volume(volume, mount_point):
    os.makedirs(mount_point, exist_ok=True)
    result = sudo_run(["mount", volume, mount_point])
    if result.returncode != 0 or not os.path.ismount(mount_point):
        log(f"mount of {volume} failed: {result.stderr.strip()}")
        return False
    return True


def unmount_volume(mount_point):
    if os.path.ismount(mount_point):
        sudo_run(["umount", mount_point])


def flash(fw, args):
    known = rp2_volumes()
    if known:
        log("ignoring RP2040 volume(s) already present before the jump: "
            + ", ".join(f"{n} ({p})" for n, p in sorted(known.items())))

    dev = via_device(args.hidraw)
    if not dev:
        return fail("macropad not found: is it plugged in, and is the udev rule installed?")
    log(f"macropad at {dev}")

    # 1. back up the keymap: the flash resets the EEPROM to the compiled keymap
    v = open_via(dev)
    if v is None:
        return fail(f"cannot open {dev}: install {UDEV_RULE} and retry")
    with v:
        try:
            keymap = v.dump_keymap()
        except RuntimeError as e:
            return fail(f"could not read the keymap: {e}")
        backup = os.path.join(args.backup_dir, "keymap-" + time.strftime("%Y%m%d-%H%M%S") + ".hex")
        try:
            os.makedirs(args.backup_dir, exist_ok=True)
            with open(backup, "w") as fh:
                fh.write(keymap.hex())
        except OSError as e:
            return fail(f"cannot write the keymap backup: {e}")
        log(f"keymap backed up: {len(keymap)} bytes -> {backup}")

        if not args.yes and not confirm_flash(fw):
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

    # 3. find the new volume, copy the image onto it
    volume = wait_for_bootloader(exclude=known)
    if not volume:
        if known:
            return fail("no new RPI-RP2 volume appeared. The volume(s) printed above were already "
                        "there before the jump; unplug the other board and retry.")
        return fail("no RPI-RP2 volume appeared: the jump did not take, try again")
    log(f"bootloader volume: {volume}")

    copy_ok = None
    owned_mount = args.mount_point is None
    mount_point = args.mount_point or tempfile.mkdtemp(prefix="rp2boot-")
    try:
        if not mount_volume(volume, mount_point):
            return fail("mount failed: is it the RPI-RP2 partition?")
        destination = os.path.join(mount_point, os.path.basename(fw))
        if os.path.islink(destination):
            return fail(f"{destination} is a symlink; refusing to write through it")
        try:
            subprocess.run(["sudo", "cp", fw, os.path.join(mount_point, "")], check=True)
            subprocess.run(["sudo", "sync"], check=True)
            src = sha256_file(fw)
            dst = sha256_with_sudo(destination)
            if dst is None:
                log("could not read the copy back to compare it; carrying on")
            elif src != dst:
                copy_ok = False
                log("the copy does not match the source")
            else:
                copy_ok = True
                log("copied and verified")
        except subprocess.CalledProcessError as e:
            return fail(f"copying the image failed: {e}")
        finally:
            unmount_volume(mount_point)
    finally:
        if owned_mount:
            try:
                os.rmdir(mount_point)
            except OSError:
                pass

    # 4. wait for the module to reboot, then write the keymap back
    dev = wait_for_keyboard(preferred=args.hidraw)
    if not dev:
        log("the module did not come back as a keyboard")
        return fail(f"when it does, restore the keymap by hand: --restore {backup}")
    log(f"macropad back at {dev}")

    v = open_via(dev)
    if v is None:
        return fail(f"cannot open {dev}; the keymap is in {backup} and can be restored with --restore")
    restored = False
    with v:
        log("restoring the keymap ...")
        try:
            restored = v.restore_keymap(keymap)
            if restored:
                log("  keymap restored and verified")
        except RuntimeError as e:
            log(f"  restore failed: {e}")
        print_status(v)
    if not restored:
        return fail(f"KEYMAP RESTORE FAILED; put it back by hand: --restore {backup}")
    if copy_ok is False:
        return fail("the copy did not match the source; the image on the module may be bad, "
                    "so consider flashing again or restoring Framework's stock image")

    # 5. optional: run a host-side command and show what it makes of it
    if args.host_command:
        run_host_command(args.host_command)
    return 0


def run_host_command(command):
    log(f"running: {command}")
    try:
        result = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=15)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        log(f"  could not run it: {e}")
        return
    output = (result.stdout or result.stderr).strip()
    for line in output.splitlines():
        log(f"  {line}")


def read_hex_keymap(path):
    try:
        with open(path) as fh:
            data = bytes.fromhex(fh.read())
    except (OSError, ValueError) as e:
        log(f"cannot read {path} as hex: {e}")
        return None
    if len(data) != KEYMAP_SIZE:
        log(f"{path} is {len(data)} bytes, expected {KEYMAP_SIZE}")
        return None
    return data


def main():
    p = argparse.ArgumentParser(
        description="Flash the Framework Laptop 16 RGB Macropad and keep its keymap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Every path defaults to somewhere next to this script. "
               "See docs/FLASHING.md for what each step does.")
    p.add_argument("firmware", nargs="?", default=DEFAULT_FIRMWARE,
                   help="UF2 image to flash (default: firmware-panel-palette.uf2 next to this script)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true",
                      help="print layer colour and diagnostics, change nothing")
    mode.add_argument("--dump", metavar="FILE",
                      help="save the EEPROM keymap to FILE as hex, change nothing")
    mode.add_argument("--restore", metavar="FILE",
                      help="write a keymap from FILE back to the module and verify it")
    p.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR,
                   help=f"where the automatic keymap backup goes (default: {DEFAULT_BACKUP_DIR})")
    p.add_argument("--mount-point", metavar="DIR",
                   help="mount the bootloader volume here instead of a temporary directory")
    p.add_argument("--hidraw", metavar="DEV",
                   help="use this hidraw node instead of looking the module up by USB id")
    p.add_argument("--host-command", metavar="CMD",
                   help="optional command to run at the end and print the output of")
    p.add_argument("--expect-sha256", metavar="HEX",
                   help="refuse to flash unless the image has this sha256 "
                        "(default: use the .sha256 file next to the image, if there is one)")
    p.add_argument("--yes", action="store_true",
                   help="do not ask before writing to the module")
    args = p.parse_args()

    if args.status or args.dump or args.restore:
        dev = via_device(args.hidraw)
        if not dev:
            return fail("macropad not found: is it plugged in?")
        log(f"macropad at {dev}")
        v = open_via(dev)
        if v is None:
            return fail(f"cannot open {dev}: is the udev rule in {UDEV_RULE} installed?")
        with v:
            if args.status:
                print_status(v)
                return 0
            try:
                if args.dump:
                    keymap = v.dump_keymap()
                    try:
                        os.makedirs(os.path.dirname(os.path.abspath(args.dump)), exist_ok=True)
                        with open(args.dump, "w") as fh:
                            fh.write(keymap.hex())
                    except OSError as e:
                        return fail(f"cannot write {args.dump}: {e}")
                    log(f"keymap saved: {len(keymap)} bytes -> {args.dump}")
                    return 0
                data = read_hex_keymap(args.restore)
                if data is None:
                    return 1
                if v.restore_keymap(data):
                    log(f"keymap restored from {args.restore} and verified")
                    return 0
                return fail("keymap restore failed: the read-back does not match")
            except RuntimeError as e:
                return fail(str(e))

    size = check_image(args.firmware)
    if size is None:
        return 1
    expected = args.expect_sha256 or expected_sha256(args.firmware)
    if expected:
        actual = sha256_file(args.firmware)
        if actual != expected.lower():
            return fail(f"sha256 of {args.firmware} is {actual}, expected {expected}; refusing to flash")
        log(f"image: {args.firmware} ({size} bytes, sha256 verified)")
    else:
        log(f"image: {args.firmware} ({size} bytes, no sha256 to compare against)")
    return flash(args.firmware, args)


if __name__ == "__main__":
    sys.exit(main())
