from __future__ import annotations

import selectors
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .clock_sync import ClockSynchronizer
from .protocol import SYNC_RESPONSE_TYPE, decode_sync_message, encode_sync_message, require_json_int, unpack_data_packet
from .testbed import DevicePlan, TestbedConfig


@dataclass(frozen=True)
class PiSample:
    source_id: int
    name: str
    sequence: int
    sender_time_ns: int
    corrected_time_ns: int | None
    receiver_time_ns: int
    values: tuple[float, ...]
    clock_offset_us: float | None
    clock_drift_ppm: float | None
    sync_rtt_us: float | None


@dataclass
class _PiState:
    device: DevicePlan
    synchronizer: ClockSynchronizer
    latest: PiSample | None = None
    last_sequence: int | None = None
    received: int = 0
    missing: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    crc_errors: int = 0


class PiReceiver:
    """Receive UTB4 Pi data, synchronize clocks, record callbacks, and retain latest samples."""

    def __init__(
        self,
        config: TestbedConfig,
        devices: tuple[DevicePlan, ...],
        sample_callback: Callable[[PiSample], None] | None = None,
    ) -> None:
        self.config = config
        self.devices = devices
        self.sample_callback = sample_callback
        self._states = {
            device.source_id: _PiState(device, ClockSynchronizer(config.sync.sample_window))
            for device in devices
        }
        self._pending_sync: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._selector = selectors.DefaultSelector()
        self._data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._data_socket.bind((config.controller.bind_ip, config.controller.data_port))
        self._data_socket.setblocking(False)
        self._sync_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sync_socket.bind((config.controller.bind_ip, 0))
        self._sync_socket.setblocking(False)
        self._selector.register(self._data_socket, selectors.EVENT_READ, "data")
        self._selector.register(self._sync_socket, selectors.EVENT_READ, "sync")

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._closed:
            raise RuntimeError("PiReceiver cannot be restarted after stop()")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._closed:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        for sock in (self._data_socket, self._sync_socket):
            try:
                self._selector.unregister(sock)
            except Exception:
                pass
            sock.close()
        self._selector.close()
        self._closed = True

    def latest_samples(self) -> dict[int, PiSample]:
        with self._lock:
            return {sid: state.latest for sid, state in self._states.items() if state.latest is not None}

    def stats(self) -> dict[int, dict[str, int]]:
        with self._lock:
            return {
                sid: {
                    "received": state.received,
                    "missing": state.missing,
                    "duplicates": state.duplicates,
                    "out_of_order": state.out_of_order,
                    "crc_errors": state.crc_errors,
                }
                for sid, state in self._states.items()
            }

    def _send_sync_requests(self) -> None:
        for source_id, state in self._states.items():
            nonce = uuid.uuid4().hex
            t0 = time.time_ns()
            self._pending_sync[nonce] = (source_id, t0)
            self._sync_socket.sendto(
                encode_sync_message({
                    "type": "sync_request",
                    "source_id": source_id,
                    "nonce": nonce,
                    "t0_receiver_send_ns": t0,
                }),
                (state.device.data_ip, state.device.sync_port),
            )

    def _process_sync(self, data: bytes, sender: tuple[str, int]) -> None:
        t3 = time.time_ns()
        try:
            message = decode_sync_message(data)
        except (UnicodeDecodeError, ValueError):
            return
        if message.get("type") != SYNC_RESPONSE_TYPE or not isinstance(message.get("nonce"), str):
            return
        pending = self._pending_sync.pop(message["nonce"], None)
        if pending is None:
            return
        expected_source_id, t0 = pending
        state = self._states.get(expected_source_id)
        if state is None or sender[0] != state.device.data_ip:
            return
        try:
            source_id = require_json_int(message, "source_id")
            t1 = require_json_int(message, "t1_sender_receive_ns")
            t2 = require_json_int(message, "t2_sender_send_ns")
        except ValueError:
            return
        if source_id != expected_source_id:
            return
        state.synchronizer.add_exchange(t0, t1, t2, t3)

    def _process_data(self, data: bytes, sender: tuple[str, int]) -> None:
        receiver_time_ns = time.time_ns()
        try:
            packet = unpack_data_packet(data)
        except ValueError:
            return
        state = self._states.get(packet.source_id)
        if state is None or sender[0] != state.device.data_ip:
            return
        callback_sample: PiSample | None = None
        with self._lock:
            state.received += 1
            if not packet.crc_ok:
                state.crc_errors += 1
                return
            if state.last_sequence is not None:
                if packet.sequence == state.last_sequence:
                    state.duplicates += 1
                elif packet.sequence < state.last_sequence:
                    state.out_of_order += 1
                elif packet.sequence > state.last_sequence + 1:
                    state.missing += packet.sequence - state.last_sequence - 1
            if state.last_sequence is None or packet.sequence > state.last_sequence:
                state.last_sequence = packet.sequence

            estimate = state.synchronizer.estimate()
            corrected_time_ns = None
            offset_us = drift_ppm = rtt_us = None
            if estimate is not None:
                corrected_time_ns = estimate.correct_sender_time(packet.sender_time_ns, receiver_time_ns)
                offset_us = estimate.offset_at(receiver_time_ns) / 1000.0
                drift_ppm = estimate.drift_ppm
                rtt_us = estimate.round_trip_delay_ns / 1000.0
            callback_sample = PiSample(
                source_id=packet.source_id,
                name=state.device.name,
                sequence=packet.sequence,
                sender_time_ns=packet.sender_time_ns,
                corrected_time_ns=corrected_time_ns,
                receiver_time_ns=receiver_time_ns,
                values=packet.values,
                clock_offset_us=offset_us,
                clock_drift_ppm=drift_ppm,
                sync_rtt_us=rtt_us,
            )
            state.latest = callback_sample
        if self.sample_callback is not None and callback_sample is not None:
            self.sample_callback(callback_sample)

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
                        data, sender = sock.recvfrom(4096)
                    except BlockingIOError:
                        break
                    if key.data == "data":
                        self._process_data(data, sender)
                    else:
                        self._process_sync(data, sender)
