from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .testbed import SdrConfig, SdrReceiverPlan


@dataclass(frozen=True)
class SdrSample:
    node: int
    time_ns: int
    measurement_received_time_ns: int
    value: float


@dataclass(frozen=True)
class SdrSnapshot:
    time_ns: int
    samples: dict[int, SdrSample]


@dataclass(frozen=True)
class SdrReceiverStatus:
    node: int
    endpoint: str
    state: str
    last_receive_time_ns: int | None = None
    error: str = ""


@dataclass
class _ReceiverState:
    plan: SdrReceiverPlan
    latest_value: float | None = None
    last_receive_time_ns: int | None = None
    error: str = ""


class SdrReceiver:
    """Collect all configured SDR ZMQ streams, retain each latest per-message average, and sample them at one controller-side rate."""

    def __init__(
        self,
        config: SdrConfig,
        *,
        snapshot_callback: Callable[[SdrSnapshot], None] | None = None,
    ) -> None:
        if config.recording_rate_hz <= 0:
            raise ValueError("SDR recording rate must be positive")
        if not config.receivers:
            raise ValueError("At least one SDR receiver is required")

        self.config = config
        self.snapshot_callback = snapshot_callback
        self._states = {receiver.node: _ReceiverState(receiver) for receiver in config.receivers}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_samples: dict[int, SdrSample] = {}
        self._fatal_error = ""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._started.clear()
        self._fatal_error = ""
        self._thread = threading.Thread(target=self._run, name="sdr-zmq-receiver", daemon=True)
        self._thread.start()
        if not self._started.wait(timeout=2.0):
            self.stop()
            raise RuntimeError("SDR receiver thread did not initialize")
        if self._fatal_error:
            error = self._fatal_error
            self.stop()
            raise RuntimeError(error)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def latest_samples(self) -> dict[int, SdrSample]:
        with self._lock:
            return dict(self._latest_samples)

    def statuses(self) -> dict[int, SdrReceiverStatus]:
        with self._lock:
            fatal = self._fatal_error
            statuses: dict[int, SdrReceiverStatus] = {}
            running = self._thread is not None and self._thread.is_alive()
            for node, state in self._states.items():
                error = state.error or fatal
                if error:
                    status = "error"
                elif state.last_receive_time_ns is not None:
                    status = "receiving"
                elif running:
                    status = "waiting"
                else:
                    status = "stopped"
                statuses[node] = SdrReceiverStatus(
                    node=node,
                    endpoint=state.plan.endpoint,
                    state=status,
                    last_receive_time_ns=state.last_receive_time_ns,
                    error=error,
                )
            return statuses

    @staticmethod
    def _decode_float32_values(message: bytes) -> np.ndarray:
        if len(message) < 4 or len(message) % 4:
            raise ValueError(f"expected one or more float32 values, received {len(message)} bytes")
        return np.frombuffer(message, dtype=np.float32, count=-1)

    @classmethod
    def _decode_latest_float(cls, message: bytes) -> float:
        """Legacy helper retained for comparison with the previous last-float behavior."""
        return float(cls._decode_float32_values(message)[-1])

    @classmethod
    def _decode_average_power(cls, message: bytes) -> float:
        """Match get_power_measurements.py: np.average() over the newest float32 message."""
        return float(np.average(cls._decode_float32_values(message)))

    def _record_message(self, node: int, message: bytes) -> None:
        try:
            value = self._decode_average_power(message)
        except ValueError as exc:
            with self._lock:
                self._states[node].error = str(exc)
            return
        received_time_ns = time.time_ns()
        with self._lock:
            state = self._states[node]
            state.latest_value = value
            state.last_receive_time_ns = received_time_ns
            state.error = ""

    def _sample_latest(self) -> None:
        sample_time_ns = time.time_ns()
        with self._lock:
            samples = {
                node: SdrSample(
                    node=node,
                    time_ns=sample_time_ns,
                    measurement_received_time_ns=state.last_receive_time_ns,
                    value=state.latest_value,
                )
                for node, state in self._states.items()
                if state.latest_value is not None and state.last_receive_time_ns is not None
            }
            self._latest_samples = samples
        if samples and self.snapshot_callback is not None:
            self.snapshot_callback(SdrSnapshot(sample_time_ns, samples))

    def _run(self) -> None:
        sockets = []
        try:
            import zmq

            context = zmq.Context.instance()
            poller = zmq.Poller()
            socket_to_node: dict[object, int] = {}
            for receiver in self.config.receivers:
                sock = context.socket(zmq.SUB)
                sock.setsockopt(zmq.SUBSCRIBE, b"")
                sock.setsockopt(zmq.CONFLATE, 1)
                sock.setsockopt(zmq.LINGER, 0)
                sock.connect(receiver.endpoint)
                poller.register(sock, zmq.POLLIN)
                sockets.append(sock)
                socket_to_node[sock] = receiver.node

            period_ns = max(1, round(1_000_000_000.0 / self.config.recording_rate_hz))
            next_sample_ns = time.perf_counter_ns()
            self._started.set()

            while not self._stop.is_set():
                now_ns = time.perf_counter_ns()
                until_sample_ns = max(0, next_sample_ns - now_ns)
                timeout_ms = max(0, min(50, int(until_sample_ns / 1_000_000)))
                try:
                    events = dict(poller.poll(timeout_ms))
                except zmq.ZMQError as exc:
                    if self._stop.is_set():
                        break
                    raise RuntimeError(f"ZeroMQ poll failed: {exc}") from exc

                for sock, event in events.items():
                    if not event & zmq.POLLIN:
                        continue
                    node = socket_to_node[sock]
                    while True:
                        try:
                            message = sock.recv(flags=zmq.NOBLOCK)
                        except zmq.Again:
                            break
                        self._record_message(node, message)

                now_ns = time.perf_counter_ns()
                if now_ns >= next_sample_ns:
                    self._sample_latest()
                    next_sample_ns += period_ns
                    if now_ns - next_sample_ns > period_ns:
                        next_sample_ns = now_ns + period_ns
        except Exception as exc:
            with self._lock:
                self._fatal_error = f"{type(exc).__name__}: {exc}"
            self._started.set()
        finally:
            for sock in sockets:
                try:
                    sock.close(0)
                except Exception:
                    pass
            self._started.set()
