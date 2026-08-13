from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .motive_receiver import MotiveFrame, MotiveReceiver
from .pi_receiver import PiReceiver, PiSample
from .recording import CsvSessionRecorder
from .rpi_udp_controller import NodeResult, RemoteController
from .testbed import DevicePlan, TestbedConfig


@dataclass(frozen=True)
class SessionStartResult:
    pi_results: tuple[NodeResult, ...]
    recording_directory: Path | None


class LiveAcquisitionSession:
    """Shared backend used by the GUI and the headless runner."""

    def __init__(
        self,
        config: TestbedConfig,
        devices: tuple[DevicePlan, ...],
        *,
        use_pis: bool,
        use_motive: bool,
        record: bool,
        name: str,
        output_directory: Path | str | None = None,
        install_pis: bool = False,
        set_pi_time: bool = False,
        leave_pis_running: bool = False,
    ) -> None:
        self.config = config
        self.devices = devices
        self.use_pis = use_pis
        self.use_motive = use_motive
        self.record = record
        self.name = name
        self.output_directory = Path(output_directory or config.controller.output_directory)
        self.install_pis = install_pis
        self.set_pi_time = set_pi_time
        self.leave_pis_running = leave_pis_running
        self.remote = RemoteController(config)
        self.recorder: CsvSessionRecorder | None = None
        self.pi_receiver: PiReceiver | None = None
        self.motive_receiver: MotiveReceiver | None = None
        self.started_nodes: tuple[DevicePlan, ...] = ()
        self.started_at_monotonic: float | None = None

    def start(self) -> SessionStartResult:
        results: list[NodeResult] = []

        # Deployment and coarse clock setting happen before any live receiver/recording
        # is started, so clock changes cannot occur during a recorded stream.
        if self.use_pis:
            if self.install_pis:
                install_results = self.remote.run_parallel(self.devices, self.remote.install)
                results.extend(install_results)
                if not all(result.success for result in install_results):
                    raise RuntimeError(self._result_errors("Pi install failed", install_results))
            if self.set_pi_time:
                time_results = self.remote.run_parallel(self.devices, self.remote.set_time)
                results.extend(time_results)
                if not all(result.success for result in time_results):
                    raise RuntimeError(self._result_errors("Pi time setting failed", time_results))

        if self.record:
            self.recorder = CsvSessionRecorder(self.output_directory, self.name)

        if self.use_pis:
            self.pi_receiver = PiReceiver(
                self.config,
                self.devices,
                sample_callback=self.recorder.record_pi if self.recorder else None,
            )
            self.pi_receiver.start()
            start_results = self.remote.run_parallel(self.devices, self.remote.start)
            results.extend(start_results)
            self.started_nodes = tuple(
                device
                for device, result in zip(self.devices, start_results)
                if result.state == "started"
            )
            if not all(result.success for result in start_results):
                raise RuntimeError(self._result_errors("Pi sender start failed", start_results))

        if self.use_motive:
            self.motive_receiver = MotiveReceiver(
                self.config.motive,
                frame_callback=self.recorder.record_motive if self.recorder else None,
            )
            self.motive_receiver.start()

        # Start CSV writing only after all selected communication paths are active.
        if self.recorder is not None:
            self.recorder.start()

        self.started_at_monotonic = time.monotonic()
        return SessionStartResult(
            pi_results=tuple(results),
            recording_directory=self.recorder.paths.directory if self.recorder else None,
        )

    def stop(self) -> None:
        elapsed = None if self.started_at_monotonic is None else time.monotonic() - self.started_at_monotonic
        pi_stats = self.pi_stats()
        motive_frames = 0 if self.motive_receiver is None else self.motive_receiver.frames_received
        latest_motive = self.latest_motive_frame()
        if self.motive_receiver is not None:
            self.motive_receiver.stop()
            self.motive_receiver = None
        if self.pi_receiver is not None:
            self.pi_receiver.stop()
            self.pi_receiver = None
        if self.use_pis and not self.leave_pis_running and self.started_nodes:
            self.remote.run_parallel(self.started_nodes, self.remote.stop)
            self.started_nodes = ()
        if self.recorder is not None:
            self.recorder.close()
            lines = [
                "Raspberry Pi / Motive acquisition summary",
                f"Elapsed seconds: {0.0 if elapsed is None else elapsed:.6f}",
                f"CSV writer drops: {self.recorder.dropped_rows}",
                f"Pi CSV: {self.recorder.paths.pi_csv.name}",
                f"Motive CSV: {self.recorder.paths.motive_csv.name}",
                "",
            ]
            for source_id, stats in sorted(pi_stats.items()):
                lines.extend([
                    f"Pi source {source_id}",
                    f"  Received: {stats['received']}",
                    f"  Missing: {stats['missing']}",
                    f"  Duplicates: {stats['duplicates']}",
                    f"  Out of order: {stats['out_of_order']}",
                    f"  CRC errors: {stats['crc_errors']}",
                    "",
                ])
            lines.extend([
                f"Motive frames received: {motive_frames}",
                f"Latest Motive frame: {'' if latest_motive is None else latest_motive.frame_number}",
            ])
            (self.recorder.paths.directory / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def latest_pi_samples(self) -> dict[int, PiSample]:
        return {} if self.pi_receiver is None else self.pi_receiver.latest_samples()

    def latest_motive_frame(self) -> MotiveFrame | None:
        return None if self.motive_receiver is None else self.motive_receiver.latest_frame()

    def pi_stats(self) -> dict[int, dict[str, int]]:
        return {} if self.pi_receiver is None else self.pi_receiver.stats()

    @staticmethod
    def _result_errors(prefix: str, results: list[NodeResult]) -> str:
        details = []
        for result in results:
            if result.success:
                continue
            detail = result.error or result.message or result.state
            details.append(f"node {result.node}: {detail}")
        return prefix + ("; " + "; ".join(details) if details else "")
