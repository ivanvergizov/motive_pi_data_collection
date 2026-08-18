from __future__ import annotations

import csv
import queue
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motive_receiver import MotiveFrame
    from .pi_receiver import PiSample


@dataclass(frozen=True)
class RecordingPaths:
    directory: Path
    pi_csv: Path
    motive_csv: Path


class CsvSessionRecorder:
    """Write Pi and Motive CSV rows on one background thread."""

    PI_FIELDS = ["source_id", "time_ns", "value"]
    MOTIVE_FIELDS = [
        "frame_number", "received_time_ns", "rigid_body_id", "rigid_body_name",
        "tracking_valid", "position_x", "position_y", "position_z",
        "rotation_x", "rotation_y", "rotation_z", "rotation_w",
    ]

    def __init__(self, output_directory: Path | str, name: str, rate_hz: int | None = None) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = (name or "live").strip().replace(" ", "_")
        directory = Path(output_directory) / f"{clean_name}_{timestamp}"
        directory.mkdir(parents=True, exist_ok=True)

        self.paths = RecordingPaths(
            directory=directory,
            pi_csv=directory / "pi_samples.csv",
            motive_csv=directory / "motive_rigid_bodies.csv",
        )
        self._pi_file = self.paths.pi_csv.open("w", encoding="utf-8", newline="")
        self._motive_file = self.paths.motive_csv.open("w", encoding="utf-8", newline="")
        self._pi_writer = csv.DictWriter(self._pi_file, fieldnames=self.PI_FIELDS)
        self._motive_writer = csv.DictWriter(self._motive_file, fieldnames=self.MOTIVE_FIELDS)
        self._pi_writer.writeheader()
        self._motive_writer.writeheader()

        self._queue: queue.SimpleQueue[tuple[str, dict[str, object]] | None] = queue.SimpleQueue()
        self._period_ns = None if rate_hz is None else int(1_000_000_000 / rate_hz)
        self._next_pi_ns: dict[int, int] = {}
        self._next_motive_ns = 0
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def record_pi(self, sample: PiSample) -> None:
        if self._period_ns is not None:
            now = time.monotonic_ns()
            next_ns = self._next_pi_ns.get(sample.source_id, 0)
            if now < next_ns:
                return
            self._next_pi_ns[sample.source_id] = now + self._period_ns if next_ns == 0 else next_ns + self._period_ns
        self._queue.put(("pi", {
            "source_id": sample.source_id,
            "time_ns": sample.time_ns,
            "value": f"{sample.value:.12g}",
        }))

    def record_motive(self, frame: MotiveFrame) -> None:
        if self._period_ns is not None:
            now = time.monotonic_ns()
            if now < self._next_motive_ns:
                return
            self._next_motive_ns = now + self._period_ns if self._next_motive_ns == 0 else self._next_motive_ns + self._period_ns
        for body in frame.bodies.values():
            self._queue.put(("motive", {
                "frame_number": frame.frame_number,
                "received_time_ns": frame.received_time_ns,
                "rigid_body_id": body.rigid_body_id,
                "rigid_body_name": body.name,
                "tracking_valid": int(body.tracking_valid),
                "position_x": f"{body.position[0]:.12g}",
                "position_y": f"{body.position[1]:.12g}",
                "position_z": f"{body.position[2]:.12g}",
                "rotation_x": f"{body.rotation[0]:.12g}",
                "rotation_y": f"{body.rotation[1]:.12g}",
                "rotation_z": f"{body.rotation[2]:.12g}",
                "rotation_w": f"{body.rotation[3]:.12g}",
            }))

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join()
        self._pi_file.close()
        self._motive_file.close()

    def _writer(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            kind, row = item
            (self._pi_writer if kind == "pi" else self._motive_writer).writerow(row)
