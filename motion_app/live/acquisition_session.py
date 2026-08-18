from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .motive_receiver import MotiveFrame, MotiveReceiver
from .pi_receiver import PiReceiver, PiSample
from .recording import CsvSessionRecorder
from .rpi_udp_controller import NodeResult, RemoteController
from .testbed import DevicePlan, TestbedConfig


@dataclass(frozen=True)
class SessionStartResult:
    recording_directory: Path | None


class LiveAcquisitionSession:
    """Shared live backend used by the GUI and standalone runner."""

    def __init__(
        self,
        config: TestbedConfig,
        devices: tuple[DevicePlan, ...],
        *,
        use_pis: bool,
        use_motive: bool,
        record: bool,
        name: str,
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
        self.install_pis = install_pis
        self.set_pi_time = set_pi_time
        self.leave_pis_running = leave_pis_running
        self.remote = RemoteController(config)
        self.recorder: CsvSessionRecorder | None = None
        self.pi_receiver: PiReceiver | None = None
        self.motive_receiver: MotiveReceiver | None = None

    def start(self) -> SessionStartResult:
        if self.use_pis and self.install_pis:
            results = self.remote.run_parallel(self.devices, self.remote.install)
            if not all(result.success for result in results):
                raise RuntimeError(self._result_errors("Pi install failed", results))

        if self.use_pis and self.set_pi_time:
            results = self.remote.run_parallel(self.devices, self.remote.set_time)
            if not all(result.success for result in results):
                raise RuntimeError(self._result_errors("Pi time setting failed", results))

        if self.record:
            self.recorder = CsvSessionRecorder(
                self.config.controller.output_directory,
                self.name,
                self.config.recording_rate_hz,
            )

        if self.use_pis:
            self.pi_receiver = PiReceiver(
                self.config,
                self.devices,
                sample_callback=self.recorder.record_pi if self.recorder else None,
            )
            self.pi_receiver.start()
            results = self.remote.run_parallel(self.devices, self.remote.start)
            if not all(result.success for result in results):
                raise RuntimeError(self._result_errors("Pi sender start failed", results))

        if self.use_motive:
            self.motive_receiver = MotiveReceiver(
                self.config.motive,
                client_ip=self.config.controller.ip,
                frame_callback=self.recorder.record_motive if self.recorder else None,
            )
            self.motive_receiver.start()

        return SessionStartResult(
            recording_directory=self.recorder.paths.directory if self.recorder else None,
        )

    def stop(self) -> None:
        if self.motive_receiver is not None:
            self.motive_receiver.stop()
            self.motive_receiver = None
        if self.pi_receiver is not None:
            self.pi_receiver.stop()
            self.pi_receiver = None
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None
        if self.use_pis and not self.leave_pis_running and self.devices:
            results = self.remote.run_parallel(self.devices, self.remote.stop)
            if not all(result.success for result in results):
                raise RuntimeError(self._result_errors("Pi sender stop failed", results))

    def latest_pi_samples(self) -> dict[int, PiSample]:
        return {} if self.pi_receiver is None else self.pi_receiver.latest_samples()

    def latest_motive_frame(self) -> MotiveFrame | None:
        return None if self.motive_receiver is None else self.motive_receiver.latest_frame()

    @staticmethod
    def _result_errors(prefix: str, results: list[NodeResult]) -> str:
        details = [
            f"node {result.node}: {result.error or result.message or result.state}"
            for result in results
            if not result.success
        ]
        return prefix + ("; " + "; ".join(details) if details else "")
