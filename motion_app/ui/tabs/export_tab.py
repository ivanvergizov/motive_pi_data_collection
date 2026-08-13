from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import uuid

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from motion_app.core.constants import DEFAULT_PREVIEW_AA, H264_RGB_LOSSLESS, VIDEO_CODEC_OPTIONS
from motion_app.core.motive_io import TrackingSession, load_motive_rigid_body_csv
from motion_app.rendering.pyvista_scene import PyVistaRigidBodyScene
from motion_app.core.tracking_data import TrackingDataProvider, nearest_sample_index
from motion_app.exporting.video_export import (
    export_frame_count,
    find_ffmpeg,
    is_ffmpeg_executable,
    validate_ffmpeg,
)
from motion_app.ui.widgets.body_selection import BodySelectionWidget
from motion_app.ui.widgets.render_settings import RenderSettingsWidget
from motion_app.ui.widgets.session_source import SessionSourceWidget
from motion_app.ui.widgets.smoothing_controls import SmoothingControlsWidget


def _console_python() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.exists():
            return str(console)
    return sys.executable


def _duration_text(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


class ExportTab(QWidget):
    def __init__(self, anti_aliasing: str = DEFAULT_PREVIEW_AA) -> None:
        super().__init__()
        self.session: TrackingSession | None = None
        self.source_file_path: str | None = None
        self.output_file_path: str | None = None
        self.ffmpeg_path = find_ffmpeg() or ""
        self.ffmpeg_ready = bool(self.ffmpeg_path)
        self.data = TrackingDataProvider()

        self.source_widget = SessionSourceWidget("Export source")
        self.body_selection = BodySelectionWidget()
        self.smoothing = SmoothingControlsWidget("Export smoothing", "Apply export smoothing")
        self.smoothing.set_available(False)
        self.scene = PyVistaRigidBodyScene(anti_aliasing)

        self.render_settings = RenderSettingsWidget(
            "Export render settings",
            include_resolution=True,
            include_msaa=True,
            include_ssaa=True,
        )
        self.render_settings.fps_combobox.setCurrentText("60")
        self.render_settings.ssaa_combobox.setCurrentText("2x")

        self.codec_combobox = QComboBox()
        self.codec_combobox.addItems(VIDEO_CODEC_OPTIONS)
        self.codec_combobox.setCurrentText(H264_RGB_LOSSLESS)
        self.codec_combobox.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.ffmpeg_status_label = QLabel()
        self.ffmpeg_browse_button = QPushButton("Browse…")

        self.output_button = QPushButton("Select output file")
        self.output_status_label = QLabel("No output file selected.")
        self.output_status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.start_time_spinbox = QDoubleSpinBox()
        self.end_time_spinbox = QDoubleSpinBox()
        for spinbox in (self.start_time_spinbox, self.end_time_spinbox):
            spinbox.setRange(0.0, 0.0)
            spinbox.setDecimals(3)
            spinbox.setSingleStep(0.1)
            spinbox.setSuffix(" s")
            spinbox.setEnabled(False)

        self.export_button = QPushButton("Export video")
        self.export_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        self.frames_label = QLabel("Frames completed: 0 / 0")
        self.eta_label = QLabel("Estimated time left: --")
        self.elapsed_label = QLabel("Completed in: --")

        self.worker: QProcess | None = None
        self.worker_stdout = ""
        self.worker_stderr = ""
        self.worker_terminal_event: str | None = None
        self.worker_error_message = ""
        self.config_path: Path | None = None
        self.cancel_path: Path | None = None
        self.export_output_path: Path | None = None

        self.cancel_kill_timer = QTimer(self)
        self.cancel_kill_timer.setSingleShot(True)
        self.cancel_kill_timer.timeout.connect(self._force_kill_worker)

        self._build_layout()
        self._connect_signals()
        self._update_ffmpeg_status()

    def _build_layout(self) -> None:
        settings = QWidget()
        settings.setMinimumWidth(0)
        settings.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(settings)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.source_widget)
        layout.addWidget(self.body_selection)
        layout.addWidget(self.smoothing)
        layout.addWidget(self.render_settings)
        layout.addWidget(self._create_time_range_group())
        layout.addWidget(self._create_encoding_group())
        layout.addWidget(self._create_output_group())

        buttons = QHBoxLayout()
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        layout.addWidget(self._create_progress_group())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(340)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(settings)

        root = QHBoxLayout(self)
        root.addWidget(scroll)
        root.addWidget(self.scene, stretch=1)

    def _create_time_range_group(self) -> QGroupBox:
        group = QGroupBox("Export range")
        layout = QVBoxLayout(group)
        layout.addWidget(QLabel("Start time"))
        layout.addWidget(self.start_time_spinbox)
        layout.addWidget(QLabel("End time"))
        layout.addWidget(self.end_time_spinbox)
        return group

    def _create_encoding_group(self) -> QGroupBox:
        group = QGroupBox("FFmpeg encoding")
        layout = QVBoxLayout(group)
        layout.addWidget(QLabel("Codec / quality"))
        layout.addWidget(self.codec_combobox)
        row = QHBoxLayout()
        row.addWidget(self.ffmpeg_status_label, stretch=1)
        row.addWidget(self.ffmpeg_browse_button)
        layout.addLayout(row)
        return group

    def _create_output_group(self) -> QGroupBox:
        group = QGroupBox("Output file")
        layout = QVBoxLayout(group)
        layout.addWidget(self.output_button)
        layout.addWidget(self.output_status_label)
        return group

    def _create_progress_group(self) -> QGroupBox:
        group = QGroupBox("Export progress")
        layout = QVBoxLayout(group)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.frames_label)
        layout.addWidget(self.eta_label)
        layout.addWidget(self.elapsed_label)
        return group

    def _connect_signals(self) -> None:
        self.source_widget.file_selected.connect(self.load_source_csv)
        self.body_selection.selection_changed.connect(self._update_preview)
        self.smoothing.settings_changed.connect(lambda _enabled, _seconds: self._update_preview())
        self.output_button.clicked.connect(self.select_output_file)
        self.ffmpeg_browse_button.clicked.connect(self._select_ffmpeg)
        self.start_time_spinbox.valueChanged.connect(self._validate_time_range)
        self.end_time_spinbox.valueChanged.connect(self._validate_time_range)
        self.export_button.clicked.connect(self.start_export)
        self.cancel_button.clicked.connect(self.cancel_export)

    def load_source_csv(self, file_path: str) -> None:
        try:
            session = load_motive_rigid_body_csv(file_path)
        except Exception as exc:
            self.source_widget.set_status(f"Error loading CSV: {exc}")
            return
        self.set_session(session, file_path)

    def set_session(self, session: TrackingSession, source_file_path: str | None = None) -> None:
        self.session = session
        self.source_file_path = source_file_path
        self.data.set_session(session)
        self.body_selection.set_bodies(list(session.bodies))
        self.smoothing.set_available(True)
        self.scene.configure_bodies(self.data.body_display_settings)
        self.scene.set_room_bounds(self.data.room_bounds())

        duration = float(session.time[-1]) if len(session.time) else 0.0
        for spinbox in (self.start_time_spinbox, self.end_time_spinbox):
            spinbox.setRange(0.0, duration)
            spinbox.setEnabled(bool(len(session.time)))
        self.start_time_spinbox.setValue(0.0)
        self.end_time_spinbox.setValue(duration)

        source = Path(source_file_path).name if source_file_path else "Session supplied externally"
        self.source_widget.set_status(f"{source}\n{len(session.bodies)} rigid bodies | {duration:.3f} s")
        self._update_preview()
        self._update_export_button()

    def _update_preview(self) -> None:
        if self.session is None or not len(self.session.time):
            return
        time_s = float(self.start_time_spinbox.value())
        frame_idx = nearest_sample_index(self.session.time, time_s)
        frame = self.data.scene_frame(
            time_s,
            frame_idx,
            self.body_selection.selected_names(),
            self.smoothing.enabled,
            self.smoothing.seconds,
        )
        self.scene.set_frame(frame)
        self.scene.request_render()


    def _select_ffmpeg(self) -> None:
        start = str(Path(self.ffmpeg_path).parent) if self.ffmpeg_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select FFmpeg executable",
            start,
            "FFmpeg executable (ffmpeg.exe);;Executable files (*.exe);;All files (*)",
        )
        if not path:
            return

        if not is_ffmpeg_executable(path):
            QMessageBox.warning(
                self,
                "Invalid FFmpeg executable",
                "The selected file could not be run as FFmpeg. Select the actual ffmpeg.exe executable.",
            )
            return

        try:
            validate_ffmpeg(path, self.codec_combobox.currentText())
        except RuntimeError as exc:
            QMessageBox.warning(self, "FFmpeg validation failed", str(exc))
            return

        self.ffmpeg_path = path
        self.ffmpeg_ready = True
        self._update_ffmpeg_status()

    def _update_ffmpeg_status(self) -> None:
        self.ffmpeg_status_label.setText("FFmpeg: ready" if self.ffmpeg_ready else "FFmpeg: not found")
        self.ffmpeg_status_label.setToolTip(
            self.ffmpeg_path if self.ffmpeg_ready else "Use Browse to select the actual ffmpeg.exe executable."
        )
        self._update_export_button()

    def select_output_file(self) -> None:
        path_text, _ = QFileDialog.getSaveFileName(
            self, "Select export file", "", "MP4 video (*.mp4);;All files (*)"
        )
        if not path_text:
            return
        path = Path(path_text)
        if path.suffix.lower() != ".mp4":
            path = path.with_suffix(".mp4")
        self.output_file_path = str(path)
        self._set_output_label(path)
        self._update_export_button()

    def _set_output_label(self, path: Path) -> None:
        self.output_status_label.setText(path.name)
        self.output_status_label.setToolTip(str(path))

    def _validate_time_range(self, _value: float | None = None) -> None:
        if self.end_time_spinbox.value() < self.start_time_spinbox.value():
            self.end_time_spinbox.setValue(self.start_time_spinbox.value())
        self._update_preview()
        self._update_export_button()

    def _update_export_button(self) -> None:
        ready = (
            self.worker is None
            and self.session is not None
            and self.output_file_path is not None
            and self.end_time_spinbox.value() >= self.start_time_spinbox.value()
        )
        self.export_button.setEnabled(ready)

        if not ready:
            if self.session is None:
                reason = "Load a Motive CSV before exporting."
            elif self.output_file_path is None:
                reason = "Select an output MP4 file before exporting."
            elif self.end_time_spinbox.value() < self.start_time_spinbox.value():
                reason = "The export end time must not be before the start time."
            else:
                reason = "An export is already running."
            self.export_button.setToolTip(reason)
        elif not self.ffmpeg_ready:
            self.export_button.setToolTip("FFmpeg is not configured; use Browse in Encoding to select ffmpeg.exe.")
        else:
            self.export_button.setToolTip("")

    def start_export(self) -> None:
        if self.source_file_path is None or not Path(self.source_file_path).is_file():
            QMessageBox.warning(
                self,
                "Source CSV required",
                "The export worker needs the original Motive CSV file. Reload the CSV in this Export tab before exporting.",
            )
            return

        if not self.ffmpeg_ready or not is_ffmpeg_executable(self.ffmpeg_path):
            self.ffmpeg_ready = False
            QMessageBox.warning(
                self,
                "FFmpeg required",
                "FFmpeg is not configured. Use the Browse button in Encoding to select the actual ffmpeg.exe executable.",
            )
            self._update_ffmpeg_status()
            return

        try:
            validate_ffmpeg(self.ffmpeg_path, self.codec_combobox.currentText())
        except RuntimeError as exc:
            self.ffmpeg_ready = False
            self._update_ffmpeg_status()
            QMessageBox.warning(self, "FFmpeg validation failed", str(exc))
            return

        width, height = self.render_settings.resolution()
        fps = self.render_settings.fps()
        msaa = self.render_settings.msaa_samples()
        ssaa = self.render_settings.ssaa_factor()
        codec = self.codec_combobox.currentText()
        output_path = Path(self.output_file_path).with_suffix(".mp4")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        temp_dir = Path(tempfile.gettempdir())
        self.config_path = temp_dir / f"motion_export_{token}.json"
        self.cancel_path = temp_dir / f"motion_export_{token}.cancel"
        self.export_output_path = output_path
        self.worker_stdout = ""
        self.worker_stderr = ""
        self.worker_terminal_event = None
        self.worker_error_message = ""

        config = {
            "csv_path": str(Path(self.source_file_path).resolve()),
            "output_path": str(output_path.resolve()),
            "cancel_path": str(self.cancel_path.resolve()),
            "ffmpeg_path": self.ffmpeg_path,
            "codec": codec,
            "camera": self.scene.export_camera_state(),
            "selected_bodies": self.body_selection.selected_names(),
            "smoothing_enabled": self.smoothing.enabled,
            "smoothing_seconds": self.smoothing.seconds,
            "width": width,
            "height": height,
            "fps": fps,
            "msaa": msaa,
            "ssaa": ssaa,
            "start_s": float(self.start_time_spinbox.value()),
            "end_s": float(self.end_time_spinbox.value()),
        }
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        total = export_frame_count(config["start_s"], config["end_s"], fps)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(0)
        self.frames_label.setText(f"Frames completed: 0 / {total}")
        self.eta_label.setText("Estimated time left: estimating…")
        self.elapsed_label.setText("Completed in: --")

        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_worker_stdout)
        process.readyReadStandardError.connect(self._read_worker_stderr)
        process.finished.connect(self._worker_finished)
        process.errorOccurred.connect(self._worker_process_error)
        self.worker = process

        self.cancel_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self._set_configuration_enabled(False)
        project_root = Path(__file__).resolve().parents[3]
        process.setWorkingDirectory(str(project_root))
        process.start(
            _console_python(),
            ["-m", "motion_app.exporting.export_worker", "--config", str(self.config_path)],
        )

    def _read_worker_stdout(self) -> None:
        if self.worker is None:
            return
        self.worker_stdout += bytes(self.worker.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.worker_stdout:
            line, self.worker_stdout = self.worker_stdout.split("\n", 1)
            try:
                event = json.loads(line.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            self._handle_worker_event(event)

    def _read_worker_stderr(self) -> None:
        if self.worker is not None:
            self.worker_stderr += bytes(self.worker.readAllStandardError()).decode("utf-8", errors="replace")

    def _handle_worker_event(self, event: dict) -> None:
        event_type = event.get("type")
        total = int(event.get("total", 0) or 0)
        current = int(event.get("current", 0) or 0)

        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(current, total))
            self.frames_label.setText(f"Frames completed: {min(current, total)} / {total}")

        if event_type == "frame":
            self.eta_label.setText(f"Estimated time left: {_duration_text(float(event.get('eta', 0.0)))}")
        elif event_type == "complete":
            self.worker_terminal_event = "complete"
            self.eta_label.setText("Estimated time left: 0:00")
            self.elapsed_label.setText(
                f"Completed in: {_duration_text(float(event.get('elapsed_seconds', 0.0)))}"
            )
        elif event_type == "cancelled":
            self.worker_terminal_event = "cancelled"
            self.eta_label.setText("Estimated time left: cancelled")
            self.elapsed_label.setText("Completed in: --")
        elif event_type == "error":
            self.worker_terminal_event = "error"
            self.worker_error_message = str(event.get("message", "Export failed."))
            self.eta_label.setText("Estimated time left: --")

    def _worker_process_error(self, error) -> None:
        if self.worker is None or error != QProcess.ProcessError.FailedToStart:
            return
        message = f"Export worker failed to start: {self.worker.errorString()}"
        self.worker = None
        self.cancel_button.setEnabled(False)
        self._set_configuration_enabled(True)
        self._cleanup_worker_files()
        self._update_export_button()
        self._show_failure(message)

    def _worker_finished(self, exit_code: int, _exit_status) -> None:
        self.cancel_kill_timer.stop()
        if self.worker is not None:
            self._read_worker_stdout()
            self._read_worker_stderr()

        terminal = self.worker_terminal_event
        output_path = self.export_output_path
        stderr = self.worker_stderr.strip()
        self.worker = None
        self.cancel_button.setEnabled(False)
        self._set_configuration_enabled(True)
        self._cleanup_worker_files()
        self._update_export_button()

        if terminal == "complete" and exit_code == 0 and output_path is not None and output_path.is_file():
            self.progress_bar.setValue(self.progress_bar.maximum())
            self.frames_label.setText(
                f"Frames completed: {self.progress_bar.maximum()} / {self.progress_bar.maximum()}"
            )
            self.eta_label.setText("Estimated time left: 0:00")
            return

        if terminal == "cancelled":
            if output_path is not None:
                output_path.unlink(missing_ok=True)
            return

        if output_path is not None:
            output_path.unlink(missing_ok=True)

        message = self.worker_error_message or f"Export worker exited unexpectedly with code {exit_code}."
        if stderr:
            message += f"\n\nWorker stderr:\n{stderr[-3000:]}"
        self._show_failure(message)

    def cancel_export(self) -> None:
        if self.worker is None:
            return
        if self.cancel_path is not None:
            self.cancel_path.write_text("cancel", encoding="utf-8")
        self.cancel_button.setEnabled(False)
        self.eta_label.setText("Estimated time left: cancelling…")
        self.cancel_kill_timer.start(5000)

    def _force_kill_worker(self) -> None:
        if self.worker is not None and self.worker.state() != QProcess.ProcessState.NotRunning:
            self.worker.kill()

    def _cleanup_worker_files(self) -> None:
        for path in (self.config_path, self.cancel_path):
            if path is not None:
                path.unlink(missing_ok=True)
        self.config_path = None
        self.cancel_path = None

    def _show_failure(self, message: str) -> None:
        QMessageBox.critical(self, "Export failed", message)

    def _set_configuration_enabled(self, enabled: bool) -> None:
        for widget in (
            self.source_widget,
            self.body_selection,
            self.smoothing,
            self.render_settings,
            self.codec_combobox,
            self.ffmpeg_browse_button,
            self.output_button,
            self.start_time_spinbox,
            self.end_time_spinbox,
        ):
            widget.setEnabled(enabled)

    def set_global_anti_aliasing(self, anti_aliasing: str) -> None:
        self.scene.set_anti_aliasing(anti_aliasing)

    def shutdown(self) -> None:
        if self.worker is not None:
            self.worker.kill()
            self.worker.waitForFinished(2000)
            self.worker = None
        self._cleanup_worker_files()
        self.scene.shutdown()
