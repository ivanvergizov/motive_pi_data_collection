#!/usr/bin/env python3
"""Keep the newest float32 value from a GNU Radio ZMQ PUB stream."""

from __future__ import annotations

import argparse
import struct
import threading
import time

import zmq


class LatestSdrMeasurement:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:55555") -> None:
        self.endpoint = endpoint
        self.time_ns: int | None = None
        self.value: float | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self) -> None:
        socket_zmq = zmq.Context.instance().socket(zmq.SUB)
        socket_zmq.setsockopt(zmq.SUBSCRIBE, b"")
        socket_zmq.setsockopt(zmq.CONFLATE, 1)  # keep only newest ZMQ message
        socket_zmq.connect(self.endpoint)

        while True:
            message = socket_zmq.recv()
            if len(message) < 4 or len(message) % 4:
                continue

            # GNU Radio PUB Sink may send a chunk of float32 stream items.
            # The final float is the newest prediction in that chunk.
            value = struct.unpack_from("<f", message, len(message) - 4)[0]
            now_ns = time.time_ns()

            with self._lock:
                self.time_ns = now_ns
                self.value = float(value)

    def latest(self) -> tuple[int, float] | None:
        with self._lock:
            if self.time_ns is None or self.value is None:
                return None
            return self.time_ns, self.value

    def wait(self, timeout_s: float = 2.0) -> tuple[int, float]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = self.latest()
            if result is not None:
                return result
            time.sleep(0.001)
        raise TimeoutError(f"No SDR measurement received from {self.endpoint}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read the latest GNU Radio prediction.")
    parser.add_argument(
        "--endpoint",
        default="tcp://127.0.0.1:55555",
        help="ZeroMQ endpoint",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="seconds to wait (default: 2)",
    )
    args = parser.parse_args()

    reader = LatestSdrMeasurement(args.endpoint)
    time_ns, value = reader.wait(args.timeout)
    print(f"{time_ns},{value:.9g}")


if __name__ == "__main__":
    main()
