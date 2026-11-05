# SPDX-License-Identifier: GPL-2.0-or-later
"""Tests for flash-macropad.py, the parts that can be tested without hardware.

The script's file name has a hyphen, so it is loaded by path. Everything here is
pure: image validation, keymap files, the lsblk walk, and the reply matching in
Via.ask, which is exercised over a socket pair instead of a real hidraw node.
"""

import importlib.util
import os
import socket
import struct
import threading

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPT = os.path.join(REPO, "flash-macropad.py")

spec = importlib.util.spec_from_file_location("flash_macropad", SCRIPT)
fm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fm)

IMAGE = os.path.join(REPO, "firmware-panel-palette.uf2")
DEFAULT_KEYMAP = os.path.join(REPO, "keymap-dumps", "framework-default.hex")


def uf2_block(payload, block_no, total, addr=None, family=None, magic=None,
              payload_size=None, flags=None):
    """One 512-byte UF2 block with a valid header unless a test overrides it."""
    magic = magic or fm.UF2_MAGIC
    family = fm.UF2_FAMILY_RP2040 if family is None else family
    addr = fm.UF2_FLASH_BASE + block_no * 256 if addr is None else addr
    payload_size = len(payload) if payload_size is None else payload_size
    flags = fm.UF2_FLAG_FAMILY_PRESENT if flags is None else flags
    header = struct.pack("<IIIIIIII", magic[0], magic[1], flags, addr,
                         payload_size, block_no, total, family)
    return header + payload + bytes(512 - 32 - len(payload))


def write_uf2(path, blocks):
    with open(path, "wb") as fh:
        for block in blocks:
            fh.write(block)
    return str(path)


def test_shipped_image_passes_validation():
    assert fm.check_image(IMAGE) == os.path.getsize(IMAGE)


def test_shipped_image_matches_its_sidecar():
    expected = fm.expected_sha256(IMAGE)
    assert expected is not None, "the image should ship with a .sha256 sidecar"
    assert fm.sha256_file(IMAGE) == expected


def test_sidecar_missing_is_not_an_error(tmp_path):
    other = tmp_path / "image.uf2"
    other.write_bytes(open(IMAGE, "rb").read())
    assert fm.expected_sha256(str(other)) is None


def test_rejects_a_file_that_is_not_a_uf2(tmp_path):
    path = tmp_path / "notes.uf2"
    path.write_text("not an image")
    assert fm.check_image(str(path)) is None


def test_rejects_a_truncated_image(tmp_path):
    data = open(IMAGE, "rb").read()[:-100]
    path = tmp_path / "short.uf2"
    path.write_bytes(data)
    assert fm.check_image(str(path)) is None


def test_rejects_a_valid_header_followed_by_zeros(tmp_path):
    blocks = [uf2_block(bytes(256), block_no=0, total=2), bytes(512)]
    path = write_uf2(tmp_path / "zeros.uf2", blocks)
    assert fm.check_image(path) is None


def test_rejects_the_wrong_family(tmp_path):
    blocks = [uf2_block(bytes(256), block_no=0, total=1, family=0x12345678)]
    assert fm.check_image(write_uf2(tmp_path / "wrong.uf2", blocks)) is None


def test_rejects_an_address_outside_flash(tmp_path):
    blocks = [uf2_block(bytes(256), block_no=0, total=1, addr=0x20000000)]
    assert fm.check_image(write_uf2(tmp_path / "ram.uf2", blocks)) is None


def test_rejects_out_of_order_blocks(tmp_path):
    blocks = [uf2_block(bytes(256), block_no=1, total=2),
              uf2_block(bytes(256), block_no=0, total=2)]
    assert fm.check_image(write_uf2(tmp_path / "order.uf2", blocks)) is None


def test_rejects_an_oversized_payload(tmp_path):
    blocks = [uf2_block(bytes(256), block_no=0, total=1, payload_size=500)]
    assert fm.check_image(write_uf2(tmp_path / "payload.uf2", blocks)) is None


def test_rejects_a_directory(tmp_path):
    assert fm.check_image(str(tmp_path)) is None


def test_accepts_a_well_formed_two_block_image(tmp_path):
    blocks = [uf2_block(bytes([0xAA]) * 256, block_no=0, total=2),
              uf2_block(bytes([0xBB]) * 256, block_no=1, total=2)]
    path = write_uf2(tmp_path / "good.uf2", blocks)
    assert fm.check_image(path) == 1024


def test_read_hex_keymap_accepts_a_real_dump():
    data = fm.read_hex_keymap(DEFAULT_KEYMAP)
    assert data is not None
    assert len(data) == fm.KEYMAP_SIZE


def test_read_hex_keymap_rejects_the_wrong_length(tmp_path):
    path = tmp_path / "short.hex"
    path.write_text("00" * 10)
    assert fm.read_hex_keymap(str(path)) is None


def test_walk_blockdevices_flattens_children():
    nodes = [{"name": "sda", "children": [{"name": "sda1"}]}, {"name": "nvme0n1"}]
    assert [n["name"] for n in fm._walk_blockdevices(nodes)] == ["sda", "sda1", "nvme0n1"]


def test_rp2_volumes_reads_labels(monkeypatch):
    listing = {
        "blockdevices": [
            {"name": "nvme0n1", "label": None, "type": "disk", "children": [
                {"name": "nvme0n1p1", "label": "RPI-RP2", "type": "part"},
            ]},
            {"name": "sdb", "label": "RPI-RP2", "type": "disk"},
        ]
    }

    class Result:
        returncode = 0
        stdout = __import__("json").dumps(listing)

    monkeypatch.setattr(fm.subprocess, "run", lambda *a, **k: Result())
    assert fm.rp2_volumes() == {"nvme0n1p1": "/dev/nvme0n1p1", "sdb": "/dev/sdb"}


def test_wait_for_bootloader_skips_volumes_that_were_already_there(monkeypatch):
    monkeypatch.setattr(fm, "rp2_volumes", lambda: {"sda1": "/dev/sda1"})
    assert fm.wait_for_bootloader(seconds=1, exclude={"sda1"}) is None
    assert fm.wait_for_bootloader(seconds=1) == "/dev/sda1"


def _via_over_socketpair(reply):
    """A Via whose fd is one end of a socket pair; the other end answers once."""
    client, server = socket.socketpair()

    def answer():
        server.recv(32)
        server.send(bytes(reply) + bytes(32 - len(reply)))

    thread = threading.Thread(target=answer, daemon=True)
    thread.start()
    via = fm.Via.__new__(fm.Via)
    via.fd = client.fileno()
    return via, client, server, thread


def test_ask_matches_a_normal_reply():
    reply = [0x08, 0x00, 0x00, 0x11, 0x22, 0x33]
    via, client, server, thread = _via_over_socketpair(reply)
    try:
        assert via.ask([0x08, 0x00, 0x00])[:5] == [0x08, 0x00, 0x00, 0x11, 0x22]
    finally:
        client.close()
        server.close()
        thread.join(timeout=1)


def test_ask_accepts_an_unhandled_reply():
    reply = [fm.ID_UNHANDLED, 0x02, 0x01]
    via, client, server, thread = _via_over_socketpair(reply)
    try:
        answer = via.ask([0x08, 0x02, 0x01])
        assert answer is not None and answer[0] == fm.ID_UNHANDLED
    finally:
        client.close()
        server.close()
        thread.join(timeout=1)


def test_get_turns_an_unhandled_reply_into_the_sentinel():
    reply = [fm.ID_UNHANDLED, 0x00, 0xF0]
    via, client, server, thread = _via_over_socketpair(reply)
    try:
        assert via._get(0x00, 0xF0) is fm.UNHANDLED
    finally:
        client.close()
        server.close()
        thread.join(timeout=1)


def test_udev_rule_grants_only_the_seat():
    rule = open(os.path.join(REPO, "udev", "99-framework-macropad-via.rules")).read()
    assert 'TAG+="uaccess"' in rule
    assert 'ATTRS{idVendor}=="32ac"' in rule
    assert 'ATTRS{idProduct}=="0013"' in rule
    active = "\n".join(line for line in rule.splitlines() if not line.strip().startswith("#"))
    assert 'GROUP="input"' not in active, "the input group can read every input device"


def test_readme_images_exist():
    for name in ("macropad.jpg", "layers.gif", "macropad.mp4"):
        path = os.path.join(REPO, "docs", "images", name)
        assert os.path.getsize(path) > 1000, f"{name} is missing or empty"
