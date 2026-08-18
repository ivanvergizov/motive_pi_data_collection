from __future__ import annotations

from collections import deque
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from motion_app.core.constants import DEFAULT_PREVIEW_AA
from motion_app.core.motive_io import TrackingSession, load_motive_rigid_body_csv
from motion_app.core.playback_controller import PlaybackController
from motion_app.rendering.pyvista_scene import PyVistaRigidBodyScene
from motion_app.core.tracking_data import TrackingDataProvider
from motion_app.ui.widgets.body_selection import BodySelectionWidget
from motion_app.ui.widgets.playback_controls import PlaybackControlsWidget
from motion_app.ui.widgets.render_settings import RenderSettingsWidget
from motion_app.ui.widgets.session_source import SessionSourceWidget
from motion_app.ui.widgets.smoothing_controls import SmoothingControlsWidget
from motion_app.ui.widgets.sidebar import configure_sidebar


class Recorded3DPlaybackTab(QWidget):
    def __init__(self, anti_aliasing: str = DEFAULT_PREVIEW_AA) -> None:
        super().__init__()
        self.session: TrackingSession | None = None
        self.source_file_path: str | None = None
        self.data = TrackingDataProvider()
        self.playback = PlaybackController(self)

        self.source_widget = SessionSourceWidget()
        self.body_selection = BodySelectionWidget()
        self.smoothing = SmoothingControlsWidget("3D smoothing")
        self.smoothing.set_available(False)
        self.playback_controls = PlaybackControlsWidget()
        self.render_settings = RenderSettingsWidget(
            "Playback settings",
            "Frame rate controls how often the current pose is rendered.",
        )
        self.metrics_label = QLabel()
        self.metrics_label.setWordWrap(True)
        self.scene = PyVistaRigidBodyScene(anti_aliasing)

        self.render_fps = self.render_settings.fps()
        self.render_timer = QTimer(self)
        self.render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.render_timer.setSingleShot(True)
        self.render_timer.timeout.connect(self._render_tick)
        self.next_render_deadline: float | None = None
        self.render_tick_times: deque[float] = deque(maxlen=240)

        self.metrics_timer = QTimer(self)
        self.metrics_timer.setInterval(500)
        self.metrics_timer.timeout.connect(self._update_metrics)
        self.metrics_timer.start()

        self._build_layout()
        self._connect_signals()
        self._update_metrics()

    def _build_layout(self) -> None:
        settings = QWidget()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for widget in (
            self.source_widget,
            self.body_selection,
            self.smoothing,
            self.playback_controls,
            self.render_settings,
            self.metrics_label,
        ):
            settings_layout.addWidget(widget)
        settings_layout.addStretch()

        scroll = QScrollArea()
        configure_sidebar(scroll, settings, fixed_width=340)

        layout = QHBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(self.scene, stretch=1)

    def _connect_signals(self) -> None:
        self.source_widget.file_selected.connect(self.load_csv)
        self.body_selection.selection_changed.connect(self._refresh_scene)
        self.smoothing.settings_changed.connect(lambda _enabled, _seconds: self._refresh_scene())
        self.playback_controls.play_requested.connect(self._play)
        self.playback_controls.pause_requested.connect(self._pause)
        self.playback_controls.seek_requested.connect(self._seek)
        self.playback_controls.speed_changed.connect(self.playback.set_speed)
        self.render_settings.fps_combobox.currentTextChanged.connect(self._set_render_fps)

    def load_csv(self, file_path: str) -> None:
        try:
            self.set_session(load_motive_rigid_body_csv(file_path), file_path)
        except Exception as exc:
            self.source_widget.set_status(f"Error loading CSV: {exc}")

    def set_session(self, session: TrackingSession, source_file_path: str | None = None) -> None:
        self._pause(render_final_frame=False)
        self.session = session
        self.source_file_path = source_file_path
        self.data.set_session(session)
        self.body_selection.set_bodies(list(session.bodies))
        self.smoothing.set_available(True)
        self.scene.configure_bodies(self.data.body_display_settings)
        bounds = self.data.room_bounds()
        self.scene.set_room_bounds(bounds)
        self.playback.set_time_array(session.time)

        duration = float(session.time[-1]) if len(session.time) else 0.0
        self.playback_controls.set_duration(duration, bool(len(session.time)))
        self.scene.reset_metrics()
        self.render_tick_times.clear()
        self._refresh_scene()
        self._update_metrics()

        source = source_file_path or "Session supplied externally"
        self.source_widget.set_status(
            f"{source}\n{len(session.bodies)} rigid bodies | {duration:.3f} s\n"
            f"Room bounds: X {bounds.x_min:g} to {bounds.x_max:g} m | "
            f"Y {bounds.y_min:g} to {bounds.y_max:g} m | Z {bounds.z_min:g} to {bounds.z_max:g} m"
        )

    def _play(self) -> None:
        if self.session is None or not len(self.session.time):
            return
        self.playback.play()
        if not self.render_timer.isActive():
            self.next_render_deadline = time.perf_counter()
            self.render_timer.start(0)

    def _pause(self, render_final_frame: bool = True) -> None:
        self.playback.pause()
        self.render_timer.stop()
        self.next_render_deadline = None
        if render_final_frame and self.session is not None:
            self._refresh_scene()

    def _seek(self, time_s: float) -> None:
        self.playback.seek(time_s)
        self._refresh_scene()

    def _set_render_fps(self, text: str) -> None:
        self.render_fps = int(text)
        if self.playback.is_playing:
            self.render_timer.stop()
            self.next_render_deadline = time.perf_counter()
            self.render_timer.start(0)
        self._update_metrics()

    def _render_tick(self) -> None:
        if not self.playback.is_playing:
            return

        tick_start = time.perf_counter()
        self.render_tick_times.append(tick_start)
        self._render_frame(*self.playback.sample())

        period = 1.0 / self.render_fps
        deadline = (self.next_render_deadline or tick_start) + period
        now = time.perf_counter()
        self.next_render_deadline = max(deadline, now)
        delay = self.next_render_deadline - now
        self.render_timer.start(0 if delay <= 0 else max(1, round(delay * 1000)))

    def _render_frame(self, time_s: float, frame_idx: int) -> None:
        if self.session is None or not len(self.session.time):
            return
        frame = self.data.scene_frame(
            time_s,
            frame_idx,
            self.body_selection.selected_names(),
            self.smoothing.enabled,
            self.smoothing.seconds,
        )
        self.scene.set_frame(frame)
        self.scene.request_render()
        self.playback_controls.set_time(time_s, frame.sample_time_s, frame.frame_number)

    def _refresh_scene(self) -> None:
        if self.session is not None and len(self.session.time):
            self._render_frame(*self.playback.sample())

    def _update_metrics(self) -> None:
        self.metrics_label.setText(self.scene.metrics_text(self.render_fps, self.render_tick_times))

    def set_global_anti_aliasing(self, anti_aliasing: str) -> None:
        was_playing = self.playback.is_playing
        self._pause(render_final_frame=False)
        self.render_tick_times.clear()
        self.scene.set_anti_aliasing(anti_aliasing)
        self._refresh_scene()
        self._update_metrics()
        if was_playing:
            self._play()

    def shutdown(self) -> None:
        self.metrics_timer.stop()
        self.render_timer.stop()
        self.playback.pause()
        self.scene.shutdown()
