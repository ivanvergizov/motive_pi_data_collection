from __future__ import annotations

import selectors
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .protocol import pack_sync_request, unpack_data_packet, unpack_sync_response
from .testbed import DevicePlan, TestbedConfig


@dataclass(frozen=True)
class PiSample:
    source_id: int
    time_ns: int
    value: float


@dataclass
class _PiState:
    device: DevicePlan
    offset_ns: int | None = None
    latest: PiSample | None = None


class PiReceiver:
    """Receive shared Pi multicast data and maintain a basic RTT clock offset."""

    def __init__(
        self,
        config: TestbedConfig,
        devices: tuple[DevicePlan, ...],
        sample_callback: Callable[[PiSample], None] | None = None,
    ) -> None:
        self.config = config
        self.sample_callback = sample_callback
        self._states = {device.node: _PiState(device) for device in devices}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._selector = selectors.DefaultSelector()

        self._data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._data_socket.bind(("", config.controller.data_port))
        membership = socket.inet_aton(config.controller.multicast_group) + socket.inet_aton(config.controller.ip)
        self._data_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        self._data_socket.setblocking(False)

        self._sync_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sync_socket.bind((config.controller.ip, 0))
        self._sync_socket.setblocking(False)

        self._selector.register(self._data_socket, selectors.EVENT_READ, "data")
        self._selector.register(self._sync_socket, selectors.EVENT_READ, "sync")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._data_socket.close()
        self._sync_socket.close()
        self._selector.close()

    def latest_samples(self) -> dict[int, PiSample]:
        with self._lock:
            return {source_id: state.latest for source_id, state in self._states.items() if state.latest is not None}

    def _send_sync_requests(self) -> None:
        for state in self._states.values():
            t0 = time.time_ns()
            self._sync_socket.sendto(
                pack_sync_request(t0),
                (state.device.data_ip, self.config.sync.device_port),
            )

    def _process_sync(self, data: bytes) -> None:
        t3 = time.time_ns()
        try:
            source_id, t0, t1, t2 = unpack_sync_response(data)
        except ValueError:
            return
        state = self._states.get(source_id)
        if state is None:
            return
        offset_ns = ((t1 - t0) + (t2 - t3)) // 2
        with self._lock:
            state.offset_ns = offset_ns

    def _process_data(self, data: bytes) -> None:
        try:
            packet = unpack_data_packet(data)
        except ValueError:
            return
        state = self._states.get(packet.source_id)
        if state is None:
            return
        with self._lock:
            corrected_time = packet.sender_time_ns
            if state.offset_ns is not None:
                corrected_time -= state.offset_ns
            sample = PiSample(packet.source_id, corrected_time, packet.value)
            state.latest = sample
        if self.sample_callback is not None:
            self.sample_callback(sample)

    def _run(self) -> None:
        next_sync = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_sync:
                self._send_sync_requests()
                next_sync = now + self.config.sync.interval_s
            for key, _ in self._selector.select(timeout=0.05):
                sock = key.fileobj
                while True:
                    try:
                        data, _ = sock.recvfrom(4096)
                    except BlockingIOError:
                        break
                    except OSError:
                        return
                    if key.data == "data":
                        self._process_data(data)
                    else:
                        self._process_sync(data)
