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
    """Rate-limit received samples and write them on one background thread."""

    def __init__(
        self,
        output_directory: Path | str,
        name: str,
        rate_hz: int | None = None,
        pi_source_ids: tuple[int, ...] = (),
    ) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._name = (name or "live").strip().replace(" ", "_")
        directory = Path(output_directory) / f"{self._name}_{timestamp}"
        directory.mkdir(parents=True, exist_ok=True)

        self.paths = RecordingPaths(
            directory=directory,
            pi_csv=directory / "pi_samples.csv",
            motive_csv=directory / "motive_rigid_bodies.csv",
        )
        self._pi_file = self.paths.pi_csv.open("w", encoding="utf-8", newline="")
        self._motive_file = self.paths.motive_csv.open("w", encoding="utf-8", newline="")
        self._pi_writer = csv.writer(self._pi_file)
        self._motive_writer = csv.writer(self._motive_file)

        self._pi_source_ids = tuple(sorted(set(pi_source_ids)))
        self._pi_column = {source_id: index + 1 for index, source_id in enumerate(self._pi_source_ids)}
        self._pi_writer.writerow(["time_ns", *[f"rpi_{source_id}" for source_id in self._pi_source_ids]])

        self._recording_rate_hz = rate_hz
        self._period_ns = None if rate_hz is None else int(1_000_000_000 / rate_hz)
        self._next_pi_ns: dict[int, int] = {}
        self._next_motive_ns = 0

        self._motive_body_ids: tuple[int, ...] = ()
        self._motive_body_names: dict[int, str] = {}
        self._motive_first_time_ns: int | None = None
        self._motive_frame_index = 0

        self._queue: queue.SimpleQueue[tuple[str, object] | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._writer, daemon=True)
        self._thread.start()

    def record_pi(self, sample: PiSample) -> None:
        column = self._pi_column.get(sample.source_id)
        if column is None:
            return
        if self._period_ns is not None:
            now = time.monotonic_ns()
            next_ns = self._next_pi_ns.get(sample.source_id, 0)
            if now < next_ns:
                return
            self._next_pi_ns[sample.source_id] = now + self._period_ns if next_ns == 0 else next_ns + self._period_ns

        row: list[object] = [""] * (len(self._pi_source_ids) + 1)
        row[0] = sample.time_ns
        row[column] = f"{sample.value:.12g}"
        self._queue.put(("pi", row))

    def record_motive(self, frame: MotiveFrame) -> None:
        if not frame.bodies:
            return
        if self._period_ns is not None:
            now = time.monotonic_ns()
            if now < self._next_motive_ns:
                return
            self._next_motive_ns = now + self._period_ns if self._next_motive_ns == 0 else self._next_motive_ns + self._period_ns

        if not self._motive_body_ids:
            bodies = sorted(frame.bodies.values(), key=lambda body: body.rigid_body_id)
            self._motive_body_ids = tuple(body.rigid_body_id for body in bodies)
            self._motive_body_names = {body.rigid_body_id: body.name for body in bodies}
            self._queue.put(("motive_header", self._motive_header_rows()))

        if self._motive_first_time_ns is None:
            self._motive_first_time_ns = frame.received_time_ns

        row: list[object] = [
            self._motive_frame_index,
            f"{(frame.received_time_ns - self._motive_first_time_ns) / 1_000_000_000:.9f}",
        ]

        for body_id in self._motive_body_ids:
            body = frame.bodies.get(body_id)
            if body is None or not body.tracking_valid:
                row.extend([""] * 7)
            else:
                row.extend([
                    f"{body.rotation[0]:.12g}",
                    f"{body.rotation[1]:.12g}",
                    f"{body.rotation[2]:.12g}",
                    f"{body.rotation[3]:.12g}",
                    f"{body.position[0]:.12g}",
                    f"{body.position[1]:.12g}",
                    f"{body.position[2]:.12g}",
                ])

        for body_id in self._motive_body_ids:
            body = frame.bodies.get(body_id)
            row.append(1 if body is not None and body.tracking_valid else 0)

        self._motive_frame_index += 1
        self._queue.put(("motive", row))

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join()
        self._pi_file.close()
        self._motive_file.close()

    def _motive_header_rows(self) -> list[list[object]]:
        metadata = [
            "Format Version", "1.23",
            "Take Name", self._name,
            "Take Notes", "",
            "Capture Frame Rate", "",
            "Export Frame Rate", "" if self._recording_rate_hz is None else self._recording_rate_hz,
            "Capture Start Time", "",
            "Capture Start Frame", "",
            "Total Frames in Take", "",
            "Total Exported Frames", "",
            "Rotation Type", "Quaternion",
            "Length Units", "Meters",
            "Coordinate Space", "Global",
        ]

        type_row: list[object] = ["", "Type"]
        name_row: list[object] = ["", "Name"]
        id_row: list[object] = ["", "ID"]
        transform_row: list[object] = ["", ""]
        dimension_row: list[object] = ["Frame", "Time (Seconds)"]

        for body_id in self._motive_body_ids:
            name = self._motive_body_names[body_id]
            type_row.extend(["Rigid Body"] * 7)
            name_row.extend([name] * 7)
            id_row.extend([""] * 7)
            transform_row.extend(["Rotation", "Rotation", "Rotation", "Rotation", "Position", "Position", "Position"])
            dimension_row.extend(["X", "Y", "Z", "W", "X", "Y", "Z"])

        for body_id in self._motive_body_ids:
            name = self._motive_body_names[body_id]
            type_row.append("Rigid Body")
            name_row.append(name)
            id_row.append("")
            transform_row.append("Tracking Valid")
            dimension_row.append("Valid")

        return [metadata, [], type_row, name_row, id_row, transform_row, dimension_row]

    def _writer(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            kind, payload = item
            if kind == "pi":
                self._pi_writer.writerow(payload)
            elif kind == "motive":
                self._motive_writer.writerow(payload)
            else:
                self._motive_writer.writerows(payload)
