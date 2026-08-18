from __future__ import annotations

import selectors
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable


_HEADER = struct.Struct("<HH")
_INT32 = struct.Struct("<i")
_RIGID_BODY = struct.Struct("<i3f4ffh")

NAT_CONNECT = 0
NAT_SERVERINFO = 1
NAT_REQUEST_MODELDEF = 4
NAT_MODELDEF = 5
NAT_FRAMEOFDATA = 7
NAT_KEEPALIVE = 10

# OptiTrack NatNet defaults used by Motive streaming.
DEFAULT_MULTICAST_GROUP = "239.255.42.99"
DEFAULT_COMMAND_PORT = 1510
DEFAULT_DATA_PORT = 1511

# The connect packet advertises a client version, but parsing follows the stream
# version Motive reports in NAT_SERVERINFO. The laboratory server currently
# reports NatNet 3.1, which is supported below.
CLIENT_NATNET_VERSION = (3, 1, 0, 0)


@dataclass(frozen=True)
class NatNetRigidBody:
    rigid_body_id: int
    position: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    tracking_valid: bool


@dataclass(frozen=True)
class NatNetRigidBodyFrame:
    frame_number: int
    bodies: tuple[NatNetRigidBody, ...]


class NatNetRigidBodyClient:
    """Rigid-body-only NatNet 3.x client with multicast and unicast transport."""

    def __init__(
        self,
        *,
        server_ip: str,
        client_ip: str,
        frame_callback: Callable[[NatNetRigidBodyFrame], None] | None = None,
        names_callback: Callable[[dict[int, str]], None] | None = None,
        use_multicast: bool = True,
        multicast_group: str = DEFAULT_MULTICAST_GROUP,
        command_port: int = DEFAULT_COMMAND_PORT,
        data_port: int = DEFAULT_DATA_PORT,
    ) -> None:
        self.server_ip = server_ip
        self.client_ip = client_ip
        self.multicast_group = multicast_group
        self.command_port = command_port
        self.data_port = data_port
        self.frame_callback = frame_callback
        self.names_callback = names_callback
        self.use_multicast = use_multicast

        self._application_version: tuple[int, int, int, int] | None = None
        self._natnet_version: tuple[int, int, int, int] | None = None
        self._server_info = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._selector: selectors.BaseSelector | None = None
        self._command_socket: socket.socket | None = None
        self._data_socket: socket.socket | None = None

    @property
    def application_version(self) -> tuple[int, int, int, int] | None:
        return self._application_version

    @property
    def natnet_version(self) -> tuple[int, int, int, int] | None:
        return self._natnet_version

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._command_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._command_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_ip = "127.0.0.1" if self.server_ip.startswith("127.") else self.client_ip
        self._command_socket.bind((bind_ip, 0))
        self._command_socket.setblocking(False)

        self._selector = selectors.DefaultSelector()
        self._selector.register(self._command_socket, selectors.EVENT_READ, "command")

        if self.use_multicast:
            self._data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            self._data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._data_socket.bind(("", self.data_port))
            membership = socket.inet_aton(self.multicast_group) + socket.inet_aton(self.client_ip)
            self._data_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            self._data_socket.setblocking(False)
            self._selector.register(self._data_socket, selectors.EVENT_READ, "data")

        self._server_info.clear()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._send_connect()

        if not self._server_info.wait(timeout=2.0):
            self.stop()
            raise RuntimeError(f"Motive did not answer NatNet connect at {self.server_ip}:{self.command_port}")

        version = self._natnet_version
        if version is None or version[0] != 3:
            self.stop()
            shown = "unknown" if version is None else ".".join(map(str, version))
            app = self._application_version
            app_shown = "unknown" if app is None else ".".join(map(str, app))
            raise RuntimeError(
                f"This client is built for NatNet 3.x; server advertised NatNet {shown} "
                f"and Motive application {app_shown}."
            )

        self.request_model_definitions()

    def stop(self) -> None:
        self._stop.set()
        for sock in (self._command_socket, self._data_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._selector is not None:
            self._selector.close()
        self._selector = None
        self._command_socket = None
        self._data_socket = None
        self._thread = None

    def request_model_definitions(self) -> None:
        if self._command_socket is None:
            return
        self._command_socket.sendto(
            _HEADER.pack(NAT_REQUEST_MODELDEF, 0),
            (self.server_ip, self.command_port),
        )

    def _send_connect(self) -> None:
        if self._command_socket is None:
            return
        payload = bytearray(271)
        payload[:4] = b"Ping"
        payload[265:269] = bytes(CLIENT_NATNET_VERSION)
        self._command_socket.sendto(
            _HEADER.pack(NAT_CONNECT, len(payload)) + payload,
            (self.server_ip, self.command_port),
        )

    def _send_keepalive(self) -> None:
        if self._command_socket is not None:
            self._command_socket.sendto(
                _HEADER.pack(NAT_KEEPALIVE, 0),
                (self.server_ip, self.command_port),
            )

    def _run(self) -> None:
        assert self._selector is not None
        next_keepalive = time.monotonic() + 1.0
        while not self._stop.is_set():
            try:
                events = self._selector.select(timeout=0.2)
            except (OSError, ValueError):
                break
            for key, _ in events:
                sock = key.fileobj
                try:
                    data, _sender = sock.recvfrom(128 * 1024)
                except (BlockingIOError, OSError):
                    continue
                try:
                    self._process_packet(data)
                except ValueError:
                    continue

            if not self.use_multicast and time.monotonic() >= next_keepalive:
                try:
                    self._send_keepalive()
                except OSError:
                    pass
                next_keepalive = time.monotonic() + 1.0

    def _process_packet(self, data: bytes) -> None:
        if len(data) < _HEADER.size:
            return
        message_id, packet_size = _HEADER.unpack_from(data, 0)
        payload = memoryview(data)[_HEADER.size:_HEADER.size + packet_size]
        if len(payload) < packet_size:
            return

        if message_id == NAT_SERVERINFO:
            self._parse_server_info(payload)
        elif message_id == NAT_MODELDEF:
            names = self._parse_model_definitions(payload)
            if self.names_callback is not None:
                self.names_callback(names)
        elif message_id == NAT_FRAMEOFDATA:
            frame = self._parse_frame(payload)
            if self.frame_callback is not None:
                self.frame_callback(frame)

    def _parse_server_info(self, payload: memoryview) -> None:
        if len(payload) < 264:
            raise ValueError("short NAT_SERVERINFO packet")
        application_version = tuple(int(value) for value in payload[256:260])
        natnet_version = tuple(int(value) for value in payload[260:264])
        self._application_version = application_version  # type: ignore[assignment]
        self._natnet_version = natnet_version  # type: ignore[assignment]
        self._server_info.set()

    def _parse_model_definitions(self, payload: memoryview) -> dict[int, str]:
        """Walk NatNet 3.x model descriptions and retain only rigid-body names."""
        offset = 0
        dataset_count, offset = self._read_count(payload, offset, "model-definition")
        names: dict[int, str] = {}
        for _ in range(dataset_count):
            data_type, offset = self._read_i32(payload, offset)
            if data_type == 0:
                offset = self._skip_marker_set_description(payload, offset)
            elif data_type == 1:
                name, rigid_body_id, offset = self._read_legacy_rigid_body_description(payload, offset)
                if name:
                    names[rigid_body_id] = name
            elif data_type == 2:
                offset = self._skip_skeleton_description(payload, offset)
            elif data_type == 3:
                offset = self._skip_force_plate_description(payload, offset)
            elif data_type == 4:
                offset = self._skip_device_description(payload, offset)
            elif data_type == 5:
                offset = self._skip_camera_description(payload, offset)
            else:
                raise ValueError(f"unsupported NatNet legacy model-definition type {data_type}")
        return names

    def _parse_frame(self, payload: memoryview) -> NatNetRigidBodyFrame:
        """Walk only the NatNet 3.x sections preceding/including rigid bodies."""
        offset = 0
        frame_number, offset = self._read_i32(payload, offset)

        marker_set_count, offset = self._read_count(payload, offset, "marker-set")
        for _ in range(marker_set_count):
            _model_name, offset = self._read_c_string(payload, offset)
            marker_count, offset = self._read_count(payload, offset, "marker")
            offset = self._skip_bytes(payload, offset, marker_count * 12)

        unlabeled_count, offset = self._read_count(payload, offset, "unlabeled-marker")
        offset = self._skip_bytes(payload, offset, unlabeled_count * 12)

        rigid_body_count, offset = self._read_count(payload, offset, "rigid-body")
        bodies, offset = self._read_rigid_bodies(payload, offset, rigid_body_count, len(payload))
        return NatNetRigidBodyFrame(frame_number=int(frame_number), bodies=tuple(bodies))

    def _read_rigid_bodies(
        self,
        payload: memoryview,
        offset: int,
        count: int,
        section_end: int,
    ) -> tuple[list[NatNetRigidBody], int]:
        bodies: list[NatNetRigidBody] = []
        for _ in range(count):
            if offset + _RIGID_BODY.size > section_end:
                raise ValueError("short NatNet rigid-body section")
            unpacked = _RIGID_BODY.unpack_from(payload, offset)
            offset += _RIGID_BODY.size
            bodies.append(
                NatNetRigidBody(
                    rigid_body_id=int(unpacked[0]),
                    position=(float(unpacked[1]), float(unpacked[2]), float(unpacked[3])),
                    rotation=(
                        float(unpacked[4]),
                        float(unpacked[5]),
                        float(unpacked[6]),
                        float(unpacked[7]),
                    ),
                    tracking_valid=bool(int(unpacked[9]) & 0x01),
                )
            )
        return bodies, offset

    def _read_legacy_rigid_body_description(
        self,
        data: memoryview,
        offset: int,
    ) -> tuple[str, int, int]:
        name, offset = self._read_c_string(data, offset)
        rigid_body_id, offset = self._read_i32(data, offset)
        _parent_id, offset = self._read_i32(data, offset)
        offset = self._skip_bytes(data, offset, 12)  # parent-relative position
        marker_count, offset = self._read_count(data, offset, "rigid-body marker")
        offset = self._skip_bytes(data, offset, marker_count * 12)  # marker positions
        offset = self._skip_bytes(data, offset, marker_count * 4)   # active labels

        return name, int(rigid_body_id), offset

    def _skip_marker_set_description(self, data: memoryview, offset: int) -> int:
        _name, offset = self._read_c_string(data, offset)
        marker_count, offset = self._read_count(data, offset, "marker-set marker")
        for _ in range(marker_count):
            _marker_name, offset = self._read_c_string(data, offset)
        return offset

    def _skip_skeleton_description(self, data: memoryview, offset: int) -> int:
        _name, offset = self._read_c_string(data, offset)
        _skeleton_id, offset = self._read_i32(data, offset)
        rigid_body_count, offset = self._read_count(data, offset, "skeleton rigid-body")
        for _ in range(rigid_body_count):
            _name, _body_id, offset = self._read_legacy_rigid_body_description(data, offset)
        return offset

    def _skip_force_plate_description(self, data: memoryview, offset: int) -> int:
        _plate_id, offset = self._read_i32(data, offset)
        _serial, offset = self._read_c_string(data, offset)
        # width + length + origin + 12x12 calibration matrix + 4x3 corners
        offset = self._skip_bytes(data, offset, 8 + 12 + (12 * 12 * 4) + (4 * 3 * 4))
        _plate_type, offset = self._read_i32(data, offset)
        _channel_data_type, offset = self._read_i32(data, offset)
        channel_count, offset = self._read_count(data, offset, "force-plate channel")
        for _ in range(channel_count):
            _channel_name, offset = self._read_c_string(data, offset)
        return offset

    def _skip_device_description(self, data: memoryview, offset: int) -> int:
        _device_id, offset = self._read_i32(data, offset)
        _name, offset = self._read_c_string(data, offset)
        _serial, offset = self._read_c_string(data, offset)
        _device_type, offset = self._read_i32(data, offset)
        _channel_data_type, offset = self._read_i32(data, offset)
        channel_count, offset = self._read_count(data, offset, "device channel")
        for _ in range(channel_count):
            _channel_name, offset = self._read_c_string(data, offset)
        return offset

    def _skip_camera_description(self, data: memoryview, offset: int) -> int:
        _name, offset = self._read_c_string(data, offset)
        return self._skip_bytes(data, offset, 12 + 16)

    def _require_supported_version(self) -> None:
        version = self._natnet_version
        if version is None or version[0] != 3:
            raise ValueError("NatNet 3.x server information has not been received")

    @staticmethod
    def _read_i32(data: memoryview, offset: int) -> tuple[int, int]:
        if offset + 4 > len(data):
            raise ValueError("short NatNet packet")
        return _INT32.unpack_from(data, offset)[0], offset + 4

    @staticmethod
    def _read_count(data: memoryview, offset: int, label: str) -> tuple[int, int]:
        value, offset = NatNetRigidBodyClient._read_i32(data, offset)
        if value < 0:
            raise ValueError(f"invalid NatNet {label} count {value}")
        return value, offset

    @staticmethod
    def _skip_bytes(data: memoryview, offset: int, count: int) -> int:
        if count < 0 or offset + count > len(data):
            raise ValueError("short NatNet packet")
        return offset + count

    @staticmethod
    def _read_c_string(data: memoryview, offset: int) -> tuple[str, int]:
        raw = bytes(data[offset:])
        end = raw.find(b"\0")
        if end < 0:
            raise ValueError("unterminated NatNet string")
        return raw[:end].decode("utf-8", errors="replace").strip(), offset + end + 1
