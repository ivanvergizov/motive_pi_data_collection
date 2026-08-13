from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from typing import Final


MAGIC: Final[bytes] = b"UTB4"
PROTOCOL_VERSION: Final[int] = 4
PAYLOAD_VALUE_COUNT: Final[int] = 8

SYNC_REQUEST_TYPE: Final[str] = "sync_request"
SYNC_RESPONSE_TYPE: Final[str] = "sync_response"

# magic, version, source_id, sequence, acquisition wall time,
# then eight double-precision values and a CRC32.
_PACKET_WITHOUT_CRC = struct.Struct("<4sBHQQ8d")
_PACKET = struct.Struct("<4sBHQQ8dI")


@dataclass(frozen=True)
class DataPacket:
    source_id: int
    sequence: int
    sender_time_ns: int
    values: tuple[float, ...]
    crc_ok: bool


def pack_data_packet(
    *,
    source_id: int,
    sequence: int,
    sender_time_ns: int,
    values: tuple[float, ...],
) -> bytes:
    if not 1 <= source_id <= 65535:
        raise ValueError("source_id must be between 1 and 65535")
    if sequence < 0:
        raise ValueError("sequence cannot be negative")
    if sender_time_ns < 0:
        raise ValueError("sender_time_ns cannot be negative")
    if len(values) != PAYLOAD_VALUE_COUNT:
        raise ValueError(
            f"values must contain exactly {PAYLOAD_VALUE_COUNT} entries"
        )

    packet_without_crc = _PACKET_WITHOUT_CRC.pack(
        MAGIC,
        PROTOCOL_VERSION,
        source_id,
        sequence,
        sender_time_ns,
        *values,
    )
    crc = zlib.crc32(packet_without_crc) & 0xFFFFFFFF
    return packet_without_crc + struct.pack("<I", crc)


def unpack_data_packet(data: bytes) -> DataPacket:
    if len(data) != _PACKET.size:
        raise ValueError(
            f"packet length {len(data)} does not match expected {_PACKET.size}"
        )

    unpacked = _PACKET.unpack(data)
    magic = unpacked[0]
    version = unpacked[1]
    if magic != MAGIC:
        raise ValueError(f"invalid packet magic {magic!r}")
    if version != PROTOCOL_VERSION:
        raise ValueError(
            f"unsupported protocol version {version}; "
            f"expected {PROTOCOL_VERSION}"
        )

    received_crc = int(unpacked[-1])
    calculated_crc = zlib.crc32(data[:-4]) & 0xFFFFFFFF
    return DataPacket(
        source_id=int(unpacked[2]),
        sequence=int(unpacked[3]),
        sender_time_ns=int(unpacked[4]),
        values=tuple(float(value) for value in unpacked[5:13]),
        crc_ok=received_crc == calculated_crc,
    )


def encode_sync_message(message: dict[str, object]) -> bytes:
    return json.dumps(
        message,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def decode_sync_message(data: bytes) -> dict[str, object]:
    decoded = json.loads(data.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("sync message must decode to a JSON object")
    return decoded


def require_json_int(message: dict[str, object], key: str) -> int:
    value = message.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"sync message field {key!r} must be an integer")
    return value
