from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final


DATA_MAGIC: Final[bytes] = b"UTB4"
SYNC_MAGIC: Final[bytes] = b"UTBS"

# One Pi measurement: format ID, source ID, Pi timestamp, prediction value.
_DATA = struct.Struct("<4sHQf")
_SYNC_REQUEST = struct.Struct("<4sQ")
_SYNC_RESPONSE = struct.Struct("<4sHQQQ")


@dataclass(frozen=True)
class DataPacket:
    source_id: int
    sender_time_ns: int
    value: float


def pack_data_packet(*, source_id: int, sender_time_ns: int, value: float) -> bytes:
    return _DATA.pack(DATA_MAGIC, source_id, sender_time_ns, float(value))


def unpack_data_packet(data: bytes) -> DataPacket:
    if len(data) != _DATA.size:
        raise ValueError("invalid UTB4 packet length")
    magic, source_id, sender_time_ns, value = _DATA.unpack(data)
    if magic != DATA_MAGIC:
        raise ValueError("invalid UTB4 packet magic")
    return DataPacket(int(source_id), int(sender_time_ns), float(value))


def pack_sync_request(t0_receiver_send_ns: int) -> bytes:
    return _SYNC_REQUEST.pack(SYNC_MAGIC, t0_receiver_send_ns)


def unpack_sync_request(data: bytes) -> int:
    if len(data) != _SYNC_REQUEST.size:
        raise ValueError("invalid sync request length")
    magic, t0 = _SYNC_REQUEST.unpack(data)
    if magic != SYNC_MAGIC:
        raise ValueError("invalid sync request magic")
    return int(t0)


def pack_sync_response(
    *,
    source_id: int,
    t0_receiver_send_ns: int,
    t1_sender_receive_ns: int,
    t2_sender_send_ns: int,
) -> bytes:
    return _SYNC_RESPONSE.pack(
        SYNC_MAGIC,
        source_id,
        t0_receiver_send_ns,
        t1_sender_receive_ns,
        t2_sender_send_ns,
    )


def unpack_sync_response(data: bytes) -> tuple[int, int, int, int]:
    if len(data) != _SYNC_RESPONSE.size:
        raise ValueError("invalid sync response length")
    magic, source_id, t0, t1, t2 = _SYNC_RESPONSE.unpack(data)
    if magic != SYNC_MAGIC:
        raise ValueError("invalid sync response magic")
    return int(source_id), int(t0), int(t1), int(t2)
