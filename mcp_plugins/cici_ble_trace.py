"""Extract host-to-device ATT writes from Android Bluetooth HCI snoop logs."""

from __future__ import annotations

import struct
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


BTSNOOP_MAGIC = b"btsnoop\x00"
ATT_CID = 0x0004
ATT_WRITE_REQUEST = 0x12
ATT_WRITE_COMMAND = 0x52
ATT_SIGNED_WRITE_COMMAND = 0xD2


class BtsnoopParseError(ValueError):
    """Raised when a capture is missing or does not contain btsnoop data."""


@dataclass(frozen=True)
class AttWrite:
    record_index: int
    timestamp: int
    direction: str
    opcode: int
    attribute_handle: int
    payload_hex: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_capture(path: Path) -> bytes:
    """Read a raw btsnoop file or locate one inside an Android bugreport zip."""
    if not zipfile.is_zipfile(path):
        return path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if "btsnoop" in name.casefold() and not name.endswith("/")
        ]
        for name in sorted(candidates, key=_capture_candidate_rank):
            data = archive.read(name)
            if data.startswith(BTSNOOP_MAGIC):
                return data
    raise BtsnoopParseError("Bugreport zip contains no binary btsnoop log")


def parse_att_writes(data: bytes) -> list[AttWrite]:
    if len(data) < 16 or not data.startswith(BTSNOOP_MAGIC):
        raise BtsnoopParseError("Input is not a btsnoop capture")

    writes = []
    offset = 16
    record_index = 0
    while offset + 24 <= len(data):
        _, included_length, flags, _, timestamp = struct.unpack_from(
            ">IIIIQ",
            data,
            offset,
        )
        offset += 24
        packet_end = offset + included_length
        if packet_end > len(data):
            raise BtsnoopParseError("Capture ends inside a btsnoop record")
        packet = data[offset:packet_end]
        offset = packet_end
        parsed = _parse_att_write(packet, flags, record_index, timestamp)
        if parsed is not None:
            writes.append(parsed)
        record_index += 1
    return writes


def _parse_att_write(
    packet: bytes,
    flags: int,
    record_index: int,
    timestamp: int,
) -> AttWrite | None:
    direction = "controller_to_host" if flags & 1 else "host_to_controller"
    if direction != "host_to_controller":
        return None
    if packet[:1] == b"\x02":
        packet = packet[1:]
    if len(packet) < 12:
        return None

    handle_and_flags, acl_length = struct.unpack_from("<HH", packet, 0)
    packet_boundary = (handle_and_flags >> 12) & 0x3
    if packet_boundary not in (0, 2):
        return None
    acl_payload = packet[4:4 + acl_length]
    if len(acl_payload) < 8:
        return None

    l2cap_length, channel_id = struct.unpack_from("<HH", acl_payload, 0)
    if channel_id != ATT_CID:
        return None
    att = acl_payload[4:4 + l2cap_length]
    if len(att) < 3:
        return None
    opcode = att[0]
    if opcode not in {
        ATT_WRITE_REQUEST,
        ATT_WRITE_COMMAND,
        ATT_SIGNED_WRITE_COMMAND,
    }:
        return None

    attribute_handle = struct.unpack_from("<H", att, 1)[0]
    payload = att[3:]
    if opcode == ATT_SIGNED_WRITE_COMMAND and len(payload) >= 12:
        payload = payload[:-12]
    return AttWrite(
        record_index=record_index,
        timestamp=timestamp,
        direction=direction,
        opcode=opcode,
        attribute_handle=attribute_handle,
        payload_hex=payload.hex(),
    )


def _capture_candidate_rank(name: str) -> tuple[int, int]:
    lowered = name.casefold()
    exact = 0 if lowered.endswith("btsnoop_hci.log") else 1
    return exact, len(name)
