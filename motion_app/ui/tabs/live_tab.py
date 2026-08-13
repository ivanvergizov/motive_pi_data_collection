from __future__ import annotations

import math
import threading
from dataclasses import replace

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from motion_app.core.app_types import BodyDisplaySettings, BodyPose, SceneFrame
from motion_app.core.body_config import DEFAULT_BODY_TYPE, load_body_type_map
from motion_app.core.constants import DEFAULT_PREVIEW_AA, color_for_curve
from motion_app.core.room_geometry import calculate_room_bounds
from motion_app.live.acquisition_session import LiveAcquisitionSession
from motion_app.live.motive_receiver import MotiveFrame
from motion_app.live.testbed import DEFAULT_CONFIG_PATH, load_testbed, override_testbed, save_testbed
from motion_app.rendering.pyvista_scene import PyVistaRigidBodyScene
from motion_app.ui.widgets.render_settings import RenderSettingsWidget
from motion_app.ui.widgets.smoothing_controls import SmoothingControlsWidget


class LivePlaybackTab(QWidget):
    session_started = Signal(object, object)
    session_stopped = Signal(object)

    def __init__(self, anti_aliasing: str = DEFAULT_PREVIEW_AA) -> None:
        super().__init__()
        self.config_path = DEFAULT_CONFIG_PATH
        self.base_config = load_testbed(self.config_path)
        self.session: LiveAcquisitionSession | None = None
        self._starting = False
        self._stopping = False
        self._last_motive_frame = -1
        self._first_motive_time_ns: int | None = None
        self._body_names: tuple[str, ...] = ()
        self._previous_poses: dict[str, tuple[int, np.ndarray, np.ndarray]] = {}

        self.scene = PyVistaRigidBodyScene(anti_aliasing)
        self.smoothing = SmoothingControlsWidget("Live smoothing", "Apply live smoothing")
        self.render_settings = RenderSettingsWidget(
            "Live preview settings",
            "Rendering is decoupled from Motive and Pi receive rates.",
        )
        self.metrics_label = QLabel()
        self.metrics_label.setWordWrap(True)
        self.status_label = QLabel("Stopped")
        self.status_label.setWordWrap(True)

        self._create_controls()
        self._load_config_into_controls()
        self._build_layout()

        self.render_timer = QTimer(self)
        self.render_timer.timeout.connect(self._render_tick)
        self.render_settings.fps_combobox.currentTextChanged.connect(self._update_render_timer)
        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(500)
        self.metrics_timer.timeout.connect(self._update_metrics)
        self.metrics_timer.start()
        self.session_started.connect(self._handle_session_started)
        self.session_stopped.connect(self._handle_session_stopped)
        self._update_render_timer()
        self._update_metrics()

    def _create_controls(self) -> None:
        cfg = self.base_config
        self.use_pis = QCheckBox("Raspberry Pis / GNU Radio")
        self.use_pis.setChecked(True)
        self.nodes_edit = QLineEdit(self._node_selector_text())
        self.pi_network_edit = QLineEdit(cfg.device_network_prefix)
        self.management_network_edit = QLineEdit(cfg.ssh.management_prefix)
        self.sample_rate = QDoubleSpinBox()
        self.sample_rate.setRange(1.0, 100000.0)
        self.sample_rate.setDecimals(1)
        self.sample_rate.setValue(cfg.default_sample_rate_hz)
        self.sample_rate.setSuffix(" Hz")
        self.sdr_enabled = QCheckBox("GNU Radio / SDR enabled")
        self.sdr_enabled.setChecked(cfg.sdr.enabled)
        self.sdr_port = QSpinBox()
        self.sdr_port.setRange(1024, 65535)
        self.sdr_port.setValue(cfg.sdr.port)

        self.controller_ip = QLineEdit(cfg.controller.ip)
        self.bind_ip = QLineEdit(cfg.controller.bind_ip)
        self.data_port = QSpinBox()
        self.data_port.setRange(1024, 65535)
        self.data_port.setValue(cfg.controller.data_port)

        self.use_motive = QCheckBox("Motive / NatNet")
        self.use_motive.setChecked(cfg.motive.enabled)
        self.motive_server_ip = QLineEdit(cfg.motive.server_ip)
        self.motive_client_ip = QLineEdit(cfg.motive.client_ip)
        self.motive_multicast = QCheckBox("Use NatNet multicast")
        self.motive_multicast.setChecked(cfg.motive.use_multicast)

        self.record_checkbox = QCheckBox("Record CSV files")
        self.record_checkbox.setChecked(True)
        self.output_directory = QLineEdit(str(cfg.controller.output_directory))
        self.output_browse = QPushButton("Browse")
        self.output_browse.clicked.connect(self._browse_output)
        self.run_name = QLineEdit("live")

        self.install_checkbox = QCheckBox("Install/update Pi sender before start")
        self.set_time_checkbox = QCheckBox("Set Pi clocks before start")
        self.leave_running_checkbox = QCheckBox("Leave Pi senders running when stopped")

        self.save_button = QPushButton("Save settings to testbed.json")
        self.start_button = QPushButton("Start communication")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_settings)
        self.start_button.clicked.connect(self._start_session)
        self.stop_button.clicked.connect(self._stop_session)

    def _node_selector_text(self) -> str:
        nodes = [device.node for device in self.base_config.devices]
        if not nodes:
            return ""
        if nodes == list(range(nodes[0], nodes[-1] + 1)):
            return f"{nodes[0]}-{nodes[-1]}"
        return ",".join(map(str, nodes))

    def _load_config_into_controls(self) -> None:
        pass

    def _build_layout(self) -> None:
        settings = QWidget()
        layout = QVBoxLayout(settings)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._source_group())
        layout.addWidget(self._network_group())
        layout.addWidget(self._recording_group())
        layout.addWidget(self._control_group())
        layout.addWidget(self.smoothing)
        layout.addWidget(self.render_settings)
        layout.addWidget(self.metrics_label)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(390)
        scroll.setMaximumWidth(470)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(settings)
        root = QHBoxLayout(self)
        root.addWidget(scroll)
        root.addWidget(self.scene, stretch=1)

    def _source_group(self) -> QGroupBox:
        group = QGroupBox("Sources")
        form = QFormLayout(group)
        form.addRow(self.use_pis)
        form.addRow("Pi nodes", self.nodes_edit)
        form.addRow("Pi data network", self.pi_network_edit)
        form.addRow("Pi SSH network", self.management_network_edit)
        form.addRow("Pi sample rate", self.sample_rate)
        form.addRow(self.sdr_enabled)
        form.addRow("GNU Radio ZMQ port", self.sdr_port)
        form.addRow(self.use_motive)
        form.addRow("Motive server IP", self.motive_server_ip)
        form.addRow("NatNet client IP", self.motive_client_ip)
        form.addRow(self.motive_multicast)
        return group

    def _network_group(self) -> QGroupBox:
        group = QGroupBox("Controller UDP")
        form = QFormLayout(group)
        form.addRow("Controller IP", self.controller_ip)
        form.addRow("Receiver bind IP", self.bind_ip)
        form.addRow("Pi data port", self.data_port)
        return group

    def _recording_group(self) -> QGroupBox:
        group = QGroupBox("Recording")
        form = QFormLayout(group)
        form.addRow(self.record_checkbox)
        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_directory, stretch=1)
        output_layout.addWidget(self.output_browse)
        form.addRow("Output directory", output_row)
        form.addRow("Run name", self.run_name)
        return group

    def _control_group(self) -> QGroupBox:
        group = QGroupBox("Communication")
        layout = QVBoxLayout(group)
        layout.addWidget(self.install_checkbox)
        layout.addWidget(self.set_time_checkbox)
        layout.addWidget(self.leave_running_checkbox)
        layout.addWidget(self.save_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        return group

    def _browse_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Recording output directory", self.output_directory.text())
        if chosen:
            self.output_directory.setText(chosen)

    def _runtime_config(self):
        return override_testbed(
            self.base_config,
            controller_ip=self.controller_ip.text().strip(),
            bind_ip=self.bind_ip.text().strip(),
            data_port=self.data_port.value(),
            output_directory=self.output_directory.text().strip(),
            device_network_prefix=self.pi_network_edit.text().strip(),
            management_prefix=self.management_network_edit.text().strip(),
            sample_rate_hz=self.sample_rate.value(),
            sdr_enabled=self.sdr_enabled.isChecked(),
            sdr_port=self.sdr_port.value(),
            motive_enabled=self.use_motive.isChecked(),
            motive_server_ip=self.motive_server_ip.text().strip(),
            motive_client_ip=self.motive_client_ip.text().strip(),
            motive_multicast=self.motive_multicast.isChecked(),
        )

    def _save_settings(self) -> None:
        try:
            config = self._runtime_config()
            if self.nodes_edit.text().strip():
                config = replace(config, devices=config.select_devices(self.nodes_edit.text().strip()))
            save_testbed(config, self.config_path)
            self.base_config = load_testbed(self.config_path)
            self.status_label.setText(f"Saved {self.config_path}")
        except Exception as exc:
            self.status_label.setText(f"Could not save settings: {exc}")

    def _start_session(self) -> None:
        if self.session is not None or self._starting:
            return
        try:
            config = self._runtime_config()
            use_pis = self.use_pis.isChecked()
            use_motive = self.use_motive.isChecked()
            if not use_pis and not use_motive:
                raise ValueError("Select Raspberry Pis, Motive, or both.")
            devices = config.select_devices(self.nodes_edit.text().strip()) if use_pis else ()
            session = LiveAcquisitionSession(
                config,
                devices,
                use_pis=use_pis,
                use_motive=use_motive,
                record=self.record_checkbox.isChecked(),
                name=self.run_name.text().strip() or "live",
                output_directory=self.output_directory.text().strip(),
                install_pis=self.install_checkbox.isChecked(),
                set_pi_time=self.set_time_checkbox.isChecked(),
                leave_pis_running=self.leave_running_checkbox.isChecked(),
            )
        except Exception as exc:
            self.status_label.setText(f"Start settings error: {exc}")
            return

        self._starting = True
        self.start_button.setEnabled(False)
        self.status_label.setText("Starting communication...")

        def worker() -> None:
            try:
                result = session.start()
            except Exception as exc:
                try:
                    session.stop()
                except Exception:
                    pass
                self.session_started.emit(None, str(exc))
                return
            self.session_started.emit((session, result), None)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_session_started(self, payload, error) -> None:
        self._starting = False
        if error is not None:
            self.start_button.setEnabled(True)
            self.status_label.setText(f"Start failed: {error}")
            return
        session, result = payload
        self.session = session
        self.stop_button.setEnabled(True)
        self._last_motive_frame = -1
        self._first_motive_time_ns = None
        self._previous_poses.clear()
        location = "not recording" if result.recording_directory is None else str(result.recording_directory)
        self.status_label.setText(f"Running\nRecording: {location}")

    def _stop_session(self) -> None:
        if self.session is None or self._stopping:
            return
        self._stopping = True
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopping...")
        session = self.session
        self.session = None

        def worker() -> None:
            try:
                session.stop()
                error = None
            except Exception as exc:
                error = str(exc)
            self.session_stopped.emit(error)

        threading.Thread(target=worker, daemon=True).start()

    def _handle_session_stopped(self, error) -> None:
        self._stopping = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Stopped" if error is None else f"Stopped with error: {error}")

    def _update_render_timer(self, _text: str | None = None) -> None:
        fps = max(1, self.render_settings.fps())
        self.render_timer.setInterval(max(1, round(1000 / fps)))
        if not self.render_timer.isActive():
            self.render_timer.start()

    def _render_tick(self) -> None:
        session = self.session
        if session is None:
            return
        frame = session.latest_motive_frame()
        if frame is not None and frame.frame_number != self._last_motive_frame:
            self._last_motive_frame = frame.frame_number
            self._show_motive_frame(frame)
        self._update_status_runtime(session)

    def _show_motive_frame(self, frame: MotiveFrame) -> None:
        tracked = [body for body in frame.bodies.values() if body.tracking_valid]
        names = tuple(sorted(body.name for body in tracked))
        if names != self._body_names:
            configured_types = load_body_type_map()
            settings = {
                name: BodyDisplaySettings(
                    body_type=configured_types.get(name, DEFAULT_BODY_TYPE),
                    color=color_for_curve(index),
                )
                for index, name in enumerate(names)
            }
            self.scene.configure_bodies(settings)
            self._body_names = names

        poses: dict[str, BodyPose] = {}
        display_positions: dict[str, np.ndarray] = {}
        for body in tracked:
            position = np.array([body.position[0], body.position[2], body.position[1]], dtype=float)
            quaternion = np.asarray(body.rotation, dtype=float)
            position, quaternion = self._smooth_pose(body.name, position, quaternion, frame.received_time_ns)
            poses[body.name] = BodyPose(position=position, quaternion_xyzw=quaternion)
            display_positions[body.name] = position.reshape(1, 3)

        if self.scene.bounds is None and display_positions:
            self.scene.set_room_bounds(calculate_room_bounds(display_positions, minimum_padding=0.5))
        if self._first_motive_time_ns is None:
            self._first_motive_time_ns = frame.received_time_ns
        elapsed = (frame.received_time_ns - self._first_motive_time_ns) / 1e9
        scene_frame = SceneFrame(
            time_s=elapsed,
            sample_time_s=frame.motive_timestamp,
            frame_number=frame.frame_number,
            poses=poses,
        )
        self.scene.set_frame(scene_frame)
        self.scene.request_render()

    def _smooth_pose(
        self,
        name: str,
        position: np.ndarray,
        quaternion: np.ndarray,
        time_ns: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not self.smoothing.enabled:
            self._previous_poses[name] = (time_ns, position.copy(), quaternion.copy())
            return position, quaternion
        previous = self._previous_poses.get(name)
        if previous is None:
            self._previous_poses[name] = (time_ns, position.copy(), quaternion.copy())
            return position, quaternion
        previous_time, previous_position, previous_quaternion = previous
        dt = max(0.0, (time_ns - previous_time) / 1e9)
        tau = max(1e-6, self.smoothing.seconds)
        alpha = 1.0 - math.exp(-dt / tau)
        smoothed_position = previous_position + alpha * (position - previous_position)
        if float(np.dot(quaternion, previous_quaternion)) < 0.0:
            quaternion = -quaternion
        smoothed_quaternion = previous_quaternion + alpha * (quaternion - previous_quaternion)
        norm = float(np.linalg.norm(smoothed_quaternion))
        if norm > 0.0:
            smoothed_quaternion /= norm
        self._previous_poses[name] = (time_ns, smoothed_position.copy(), smoothed_quaternion.copy())
        return smoothed_position, smoothed_quaternion

    def _update_status_runtime(self, session: LiveAcquisitionSession) -> None:
        parts: list[str] = []
        if session.use_pis:
            samples = session.latest_pi_samples()
            stats = session.pi_stats()
            received = sum(item["received"] for item in stats.values())
            missing = sum(item["missing"] for item in stats.values())
            parts.append(f"Pis {len(samples)}/{len(session.devices)} | packets {received} | missing {missing}")
        if session.use_motive:
            frame = session.latest_motive_frame()
            parts.append("Motive waiting" if frame is None else f"Motive frame {frame.frame_number} | bodies {len(frame.bodies)}")
        if session.recorder is not None:
            parts.append(f"Recording {session.recorder.paths.directory.name} | writer drops {session.recorder.dropped_rows}")
        self.status_label.setText("\n".join(parts) if parts else "Running")

    def _update_metrics(self) -> None:
        self.metrics_label.setText(self.scene.metrics_text(self.render_settings.fps()))

    def set_global_anti_aliasing(self, anti_aliasing: str) -> None:
        self.scene.set_anti_aliasing(anti_aliasing)
        self.scene.request_render()
        self._update_metrics()

    def shutdown(self) -> None:
        self.metrics_timer.stop()
        self.render_timer.stop()
        if self.session is not None:
            try:
                self.session.stop()
            except Exception:
                pass
            self.session = None
        self.scene.shutdown()
