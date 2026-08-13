from __future__ import annotations

import csv
import queue
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .protocol import PAYLOAD_VALUE_COUNT

if TYPE_CHECKING:
    from .motive_receiver import MotiveFrame
    from .pi_receiver import PiSample


@dataclass(frozen=True)
class RecordingPaths:
    directory: Path
    pi_csv: Path
    motive_csv: Path


class CsvSessionRecorder:
    """Write Pi and Motive samples to separate CSVs on one background thread."""

    PI_FIELDS = [
        "source", "source_id", "sequence", "sender_time_ns", "corrected_time_ns",
        "receiver_time_ns", "clock_offset_us", "clock_drift_ppm", "sync_rtt_us",
        *[f"value_{index}" for index in range(PAYLOAD_VALUE_COUNT)],
    ]
    MOTIVE_FIELDS = [
        "frame_number", "received_time_ns", "motive_timestamp", "rigid_body_id",
        "rigid_body_name", "tracking_valid", "mean_error",
        "position_x", "position_y", "position_z",
        "rotation_x", "rotation_y", "rotation_z", "rotation_w",
    ]

    def __init__(self, output_directory: Path | str, name: str) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        clean_name = (name or "live").strip().replace(" ", "_")
        directory = Path(output_directory).expanduser() / f"{clean_name}_{timestamp}"
        directory.mkdir(parents=True, exist_ok=True)
        self.paths = RecordingPaths(
            directory=directory,
            pi_csv=directory / "pi_samples.csv",
            motive_csv=directory / "motive_rigid_bodies.csv",
        )
        self._queue: queue.Queue[tuple[str, dict[str, object]] | None] = queue.Queue(maxsize=100_000)
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._started = False
        self.dropped_rows = 0

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def record_pi(self, sample: PiSample) -> None:
        row: dict[str, object] = {
            "source": sample.name,
            "source_id": sample.source_id,
            "sequence": sample.sequence,
            "sender_time_ns": sample.sender_time_ns,
            "corrected_time_ns": "" if sample.corrected_time_ns is None else sample.corrected_time_ns,
            "receiver_time_ns": sample.receiver_time_ns,
            "clock_offset_us": "" if sample.clock_offset_us is None else f"{sample.clock_offset_us:.6f}",
            "clock_drift_ppm": "" if sample.clock_drift_ppm is None else f"{sample.clock_drift_ppm:.6f}",
            "sync_rtt_us": "" if sample.sync_rtt_us is None else f"{sample.sync_rtt_us:.6f}",
        }
        for index, value in enumerate(sample.values):
            row[f"value_{index}"] = f"{value:.12g}"
        self._put(("pi", row))

    def record_motive(self, frame: MotiveFrame) -> None:
        for body in frame.bodies.values():
            self._put(("motive", {
                "frame_number": frame.frame_number,
                "received_time_ns": frame.received_time_ns,
                "motive_timestamp": f"{frame.motive_timestamp:.9f}",
                "rigid_body_id": body.rigid_body_id,
                "rigid_body_name": body.name,
                "tracking_valid": int(body.tracking_valid),
                "mean_error": f"{body.mean_error:.9g}",
                "position_x": f"{body.position[0]:.12g}",
                "position_y": f"{body.position[1]:.12g}",
                "position_z": f"{body.position[2]:.12g}",
                "rotation_x": f"{body.rotation[0]:.12g}",
                "rotation_y": f"{body.rotation[1]:.12g}",
                "rotation_z": f"{body.rotation[2]:.12g}",
                "rotation_w": f"{body.rotation[3]:.12g}",
            }))

    def close(self) -> None:
        if not self._started:
            return
        self._queue.put(None)
        self._thread.join(timeout=5.0)
        self._started = False

    def _put(self, item: tuple[str, dict[str, object]]) -> None:
        if not self._started:
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped_rows += 1

    def _writer(self) -> None:
        with (
            self.paths.pi_csv.open("w", encoding="utf-8", newline="") as pi_file,
            self.paths.motive_csv.open("w", encoding="utf-8", newline="") as motive_file,
        ):
            pi_writer = csv.DictWriter(pi_file, fieldnames=self.PI_FIELDS)
            motive_writer = csv.DictWriter(motive_file, fieldnames=self.MOTIVE_FIELDS)
            pi_writer.writeheader()
            motive_writer.writeheader()
            while True:
                item = self._queue.get()
                if item is None:
                    break
                kind, row = item
                if kind == "pi":
                    pi_writer.writerow(row)
                else:
                    motive_writer.writerow(row)
