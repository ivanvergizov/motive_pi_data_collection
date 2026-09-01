from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .motive_receiver import MotiveFrame, MotiveReceiver
from .recording import CsvSessionRecorder
from .sdr_receiver import SdrReceiver, SdrReceiverStatus, SdrSample
from .testbed import TestbedConfig


@dataclass(frozen=True)
class SessionStartResult:
    recording_directory: Path | None


class LiveAcquisitionSession:
    """Shared live backend used by both the GUI and standalone runner."""

    def __init__(
        self,
        config: TestbedConfig,
        *,
        use_sdr: bool,
        use_motive: bool,
        record: bool,
        name: str,
    ) -> None:
        self.config = config
        self.use_sdr = use_sdr
        self.use_motive = use_motive
        self.record = record
        self.name = name
        self.recorder: CsvSessionRecorder | None = None
        self.sdr_receiver: SdrReceiver | None = None
        self.motive_receiver: MotiveReceiver | None = None

    def start(self) -> SessionStartResult:
        if not self.use_sdr and not self.use_motive:
            raise ValueError("At least one live source must be enabled")
        if self.use_sdr and not self.config.sdr.receivers:
            raise ValueError("SDR is enabled but no receivers are configured")

        try:
            if self.record:
                self.recorder = CsvSessionRecorder(
                    self.config.controller.output_directory,
                    self.name,
                    motive_rate_hz=self.config.motive.recording_rate_hz,
                    sdr_source_ids=(
                        tuple(receiver.node for receiver in self.config.sdr.receivers)
                        if self.use_sdr else ()
                    ),
                    record_motive=self.use_motive,
                )

            if self.use_sdr:
                self.sdr_receiver = SdrReceiver(
                    self.config.sdr,
                    snapshot_callback=self.recorder.record_sdr if self.recorder else None,
                )
                self.sdr_receiver.start()

            if self.use_motive:
                self.motive_receiver = MotiveReceiver(
                    self.config.motive,
                    client_ip=self.config.motive.interface_ip,
                    frame_callback=self.recorder.record_motive if self.recorder else None,
                )
                self.motive_receiver.start()
        except Exception:
            try:
                self.stop()
            except Exception:
                pass
            raise

        return SessionStartResult(
            recording_directory=self.recorder.paths.directory if self.recorder else None,
        )

    def stop(self) -> None:
        errors: list[str] = []
        if self.motive_receiver is not None:
            try:
                self.motive_receiver.stop()
            except Exception as exc:
                errors.append(f"Motive stop: {exc}")
            self.motive_receiver = None
        if self.sdr_receiver is not None:
            try:
                self.sdr_receiver.stop()
            except Exception as exc:
                errors.append(f"SDR stop: {exc}")
            self.sdr_receiver = None
        if self.recorder is not None:
            try:
                self.recorder.close()
            except Exception as exc:
                errors.append(f"recorder close: {exc}")
            self.recorder = None
        if errors:
            raise RuntimeError("; ".join(errors))

    def latest_sdr_samples(self) -> dict[int, SdrSample]:
        return {} if self.sdr_receiver is None else self.sdr_receiver.latest_samples()

    def sdr_status(self) -> dict[int, SdrReceiverStatus]:
        return {} if self.sdr_receiver is None else self.sdr_receiver.statuses()

    def latest_motive_frame(self) -> MotiveFrame | None:
        return None if self.motive_receiver is None else self.motive_receiver.latest_frame()
