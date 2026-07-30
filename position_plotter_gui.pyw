#%%

from __future__ import annotations

import sys

from dependency_check import ensure_dependencies_or_exit

ensure_dependencies_or_exit()

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import(
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QFormLayout,
)

import pyqtgraph as pg
import pyqtgraph.opengl as gl

import numpy as np

from typing import TypedDict

import time

from motive_io import load_motive_rigid_body_csv, TrackingSession

from signal_processing import smooth_tracking_positions_and_rotations

from rigid_body_gl import (
    create_body_vertices,
    make_body_mesh_item,
    transform_body_vertices,
    update_body_mesh_item,
)

from rigid_body_math import motive_positions_to_display


POSITION_SIGNAL_INDICES = {
    "Position X": 0,
    "Position Y": 1,
    "Position Z": 2
}

ROTATION_SIGNAL_INDICES = {
    "Rotation X": 0,
    "Rotation Y": 1,
    "Rotation Z": 2,
    "Rotation W": 3,
}

SIGNALS = {
    **POSITION_SIGNAL_INDICES,
    **ROTATION_SIGNAL_INDICES
    }

PLOT_COLORS = [
    "#e31212",
    "#fa7704",
    "#f7f308",
    "#2bdc0b",
    "#15dbfa",
    "#fe21f3",
    "#be018c",
    "#942f2f",
    "#934907",
    "#9d9c2f",
    "#437c39",
    "#2c808d",
    "#81217c",
    "#80002f",
    "#890346"
]

DEFAULT_PLAYBACK_MSAA_SAMPLES = 4

PLAYBACK_RESOLUTION_OPTIONS = [
    "Current widget size",
    "1280 x 720",
    "1920 x 1080",
    "2560 x 1440",
    "3840 x 2160",
]

MSAA_OPTIONS = [
    "Off",
    "2x",
    "4x",
    "8x",
    "16x",
]

SSAA_OPTIONS = [
    "1x",
    "2x",
    "3x",
    "4x",
]

def color_for_curve(curve_index: int) -> str:
    return PLOT_COLORS[curve_index % len(PLOT_COLORS)]

def configure_default_opengl_format(msaa_samples: int) -> None:
    surface_format = QSurfaceFormat()

    if msaa_samples > 0:
        surface_format.setSamples(msaa_samples)

    QSurfaceFormat.setDefaultFormat(surface_format)

class BodyDisplaySettings(TypedDict):
    shape: str
    length: float
    width: float
    height: float
    color: str

class PositionPlotterWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OptiTrack Position Plotter")
        self.resize(1400, 800)

        self.session: TrackingSession | None = None
        self.body_checkboxes: dict[str, QCheckBox] = {}
        self.signal_checkboxes: dict[str, QCheckBox] = {}

        self.display_positions: dict[str, np.ndarray] = {}
        self.display_rotations: dict[str, np.ndarray] = {}

        self.smoothed_display_positions: dict[str, np.ndarray] = {}
        self.smoothed_display_rotations: dict[str, np.ndarray] = {}

        self.current_time_s = 0.0
        self.current_frame_idx = 0
        self.mesh_items_by_body: dict[str, gl.GLMeshItem] = {}
        self.base_vertices_by_body: dict[str, np.ndarray] = {}

        self.playback_speed = 1.0
        self.playback_start_wall_time_s = 0.0
        self.playback_start_data_time_s = 0.0

        self.playback_timer = QTimer()
        self.playback_timer.timeout.connect(self.advance_3d_time)

        self.position_plot_widget = pg.PlotWidget()
        self.position_plot_widget.setBackground("w")
        self.position_plot_widget.showGrid(x=True, y=True)
        self.position_plot_widget.setLabel("bottom", "Time", units="s")
        self.position_plot_widget.setLabel("left", "Position", units="m")
        self.position_plot_widget.addLegend()

        self.rotation_plot_widget = pg.PlotWidget()
        self.rotation_plot_widget.setBackground("w")
        self.rotation_plot_widget.showGrid(x=True, y=True)
        self.rotation_plot_widget.setLabel("bottom", "Time", units="s")
        self.rotation_plot_widget.setLabel("left", "Quaternion Rotation")
        self.rotation_plot_widget.addLegend()

        self.view_3d_widget = gl.GLViewWidget()
        self.view_3d_widget.setBackgroundColor('w')
        self.view_3d_widget.setCameraPosition(
            distance=2.0,
            elevation=25.0,
            azimuth=45.0
        )

        self.body_display_settings: dict[str, BodyDisplaySettings] = {}

        self.grid_3d = gl.GLGridItem()
        self.grid_3d.setSize(x=2.0, y=2.0)
        self.grid_3d.setSpacing(x=0.1, y=0.1)

        self.grid_3d.setColor((0, 0, 0, 150))

        self.view_3d_widget.addItem(self.grid_3d)

        self.plot_tabs = QTabWidget()
        self.plot_tabs.addTab(self.position_plot_widget, "Position")
        self.plot_tabs.addTab(self.rotation_plot_widget, "Rotation")
        self.plot_tabs.addTab(self.view_3d_widget, "3D")

        self._build_layout()

    def _build_layout(self) -> None:
        root = QWidget()
        main_layout = QHBoxLayout(root)

        settings_scroll_area = QScrollArea()
        settings_scroll_area.setWidgetResizable(True)
        settings_scroll_area.setMinimumWidth(320)

        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)

        settings_scroll_area.setWidget(settings_container)

        settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        load_button = QPushButton("Load Motive CSV")
        load_button.clicked.connect(self.load_csv)

        plot_button = QPushButton("Update Plot")
        plot_button.clicked.connect(self.update_plot)

        settings_layout.addWidget(load_button)
        settings_layout.addWidget(plot_button)

        self.status_label = QLabel("No CSV loaded.")
        settings_layout.addWidget(self.status_label)

        self.body_group = QGroupBox("Rigid bodies")
        self.body_layout = QVBoxLayout()
        self.body_group.setLayout(self.body_layout)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setWidget(self.body_group)

        settings_layout.addWidget(body_scroll)

        signal_group = QGroupBox("Signals")
        signal_layout = QVBoxLayout()

        for label in SIGNALS:
            checkbox = QCheckBox(label)

            self.signal_checkboxes[label] = checkbox
            signal_layout.addWidget(checkbox)

        signal_group.setLayout(signal_layout)
        settings_layout.addWidget(signal_group)

        smoothing_group = QGroupBox("Smoothing")
        smoothing_layout = QVBoxLayout()

        self.smoothing_checkbox = QCheckBox("Apply smoothing")
        self.smoothing_checkbox.stateChanged.connect(
            self.handle_smoothing_settings_changed
        )
        smoothing_layout.addWidget(self.smoothing_checkbox)

        self.smoothing_seconds_spinbox = QDoubleSpinBox()
        self.smoothing_seconds_spinbox.setMinimum(0.00)
        self.smoothing_seconds_spinbox.setMaximum(5.00)
        self.smoothing_seconds_spinbox.setSingleStep(0.05)
        self.smoothing_seconds_spinbox.setDecimals(2)
        self.smoothing_seconds_spinbox.setValue(0.25)
        self.smoothing_seconds_spinbox.setPrefix("Window: ")
        self.smoothing_seconds_spinbox.setSuffix(" s")
        self.smoothing_seconds_spinbox.valueChanged.connect(
            self.handle_smoothing_settings_changed
        )

        smoothing_layout.addWidget(self.smoothing_seconds_spinbox)

        smoothing_group.setLayout(smoothing_layout)
        settings_layout.addWidget(smoothing_group)

        playback_group = QGroupBox("3D Playback")
        playback_layout = QVBoxLayout()

        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setMinimum(0)
        self.time_slider.setMaximum(0)
        self.time_slider.valueChanged.connect(self.set_3d_time_from_slider)

        self.time_label = QLabel("Time: 0.000 s | Frame: 0")

        self.playback_speed_spinbox = QDoubleSpinBox()
        self.playback_speed_spinbox.setMinimum(0.25)
        self.playback_speed_spinbox.setMaximum(5.00)
        self.playback_speed_spinbox.setSingleStep(0.25)
        self.playback_speed_spinbox.setValue(1.00)
        self.playback_speed_spinbox.setDecimals(2)
        self.playback_speed_spinbox.setPrefix("Speed: ")
        self.playback_speed_spinbox.setSuffix("x")
        self.playback_speed_spinbox.valueChanged.connect(self.set_playback_speed)

        self.render_fps_combobox = QComboBox()
        self.render_fps_combobox.addItems(["15", "30", "60", "120"])
        self.render_fps_combobox.setCurrentText("30")
        self.render_fps_combobox.currentTextChanged.connect(self.set_render_fps_cap)

        playback_button_layout = QHBoxLayout()

        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.play_3d)

        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_3d)

        playback_button_layout.addWidget(self.play_button)
        playback_button_layout.addWidget(self.pause_button)

        playback_layout.addWidget(self.time_label)
        playback_layout.addWidget(self.time_slider)
        playback_layout.addWidget(self.playback_speed_spinbox)
        playback_layout.addWidget(QLabel("Render FPS cap"))
        playback_layout.addWidget(self.render_fps_combobox)

        playback_layout.addWidget(QLabel("Playback resolution"))

        self.playback_resolution_combobox = QComboBox()
        self.playback_resolution_combobox.addItems(PLAYBACK_RESOLUTION_OPTIONS)
        self.playback_resolution_combobox.setCurrentText("Current widget size")
        self.playback_resolution_combobox.currentTextChanged.connect(
            self.handle_playback_render_settings_changed
        )
        playback_layout.addWidget(self.playback_resolution_combobox)

        playback_layout.addWidget(QLabel("Playback MSAA"))

        self.playback_msaa_combobox = QComboBox()
        self.playback_msaa_combobox.addItems(MSAA_OPTIONS)
        self.playback_msaa_combobox.setCurrentText("4x")
        self.playback_msaa_combobox.currentTextChanged.connect(
            self.handle_playback_render_settings_changed
        )
        playback_layout.addWidget(self.playback_msaa_combobox)

        playback_layout.addWidget(QLabel("Playback SSAA"))

        self.playback_ssaa_combobox = QComboBox()
        self.playback_ssaa_combobox.addItems(SSAA_OPTIONS)
        self.playback_ssaa_combobox.setCurrentText("1x")
        self.playback_ssaa_combobox.currentTextChanged.connect(
            self.handle_playback_render_settings_changed
        )
        playback_layout.addWidget(self.playback_ssaa_combobox)

        playback_layout.addLayout(playback_button_layout)

        playback_group.setLayout(playback_layout)
        settings_layout.addWidget(playback_group)

        export_group = self.create_export_settings_group()
        settings_layout.addWidget(export_group)

        settings_layout.addStretch()

        main_layout.addWidget(settings_scroll_area)
        main_layout.addWidget(self.plot_tabs, stretch=1)
        self.setCentralWidget(root)

    def clear_body_checkboxes(self) -> None:
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)

            if item is None:
                continue

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self.body_checkboxes.clear()

    def populate_body_checkboxes(self) -> None:
        if self.session is None:
            return
        
        self.clear_body_checkboxes()

        for body_name in self.session.bodies:
            checkbox = QCheckBox(body_name)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self.handle_body_selection_changed)

            self.body_checkboxes[body_name] = checkbox
            self.body_layout.addWidget(checkbox)

    def load_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Motive CSV",
            "",
            "CSV files (*.csv);;All files (*)",
        )

        if not file_path:
            return
        
        try:
            self.session = load_motive_rigid_body_csv(file_path)

        except Exception as exc:
            self.status_label.setText(f"Error loading CSV: {exc}")
            return
        
        self.populate_body_checkboxes()

        self.body_display_settings.clear()

        for body_index, body_name in enumerate(self.session.bodies):
            self.body_display_settings[body_name] = {
                "shape": "tetra",
                "length": 0.09,
                "width": 0.065,
                "height": 0.025,
                "color": color_for_curve(body_index),
    }

        self.clear_3d_meshes()
        self.rebuild_body_geometry_cache()

        self.display_positions.clear()
        self.display_rotations.clear()

        for body_name, body in self.session.bodies.items():
            self.display_positions[body_name] = motive_positions_to_display(
                body.position_x,
                body.position_y,
                body.position_z
            )

            self.display_rotations[body_name] = np.column_stack(
                [
                    body.rotation_x,
                    body.rotation_y,
                    body.rotation_z,
                    body.rotation_w
                ]
            )

        self.update_smoothed_tracking_data()

        duration_ms = int(round(self.session.time[-1] * 1000.0))

        self.time_slider.blockSignals(True)
        self.time_slider.setMaximum(duration_ms)
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)

        self.set_3d_time(0.0, update_slider=True)

        num_bodies = len(self.session.bodies)
        session_duration = self.session.time[-1]

        self.status_label.setText(
            f"loaded {num_bodies} rigid bodies from recording of length {session_duration} seconds"
        )

    def selected_body_names(self) -> list[str]:
        selected_names: list[str] = []

        for body_name, checkbox in self.body_checkboxes.items():
            if checkbox.isChecked():
                selected_names.append(body_name)

        return selected_names
    
    def selected_signal_labels(self) -> list[str]:
        selected_labels: list[str] = []

        for signal_label, checkbox in self.signal_checkboxes.items():
            if checkbox.isChecked():
                selected_labels.append(signal_label)

        return selected_labels
    
    def update_plot(self) -> None:
        if self.session is None:
            self.status_label.setText("Load a CSV before plotting")
            return

        selected_bodies = self.selected_body_names()
        selected_signals = self.selected_signal_labels()

        if not selected_bodies:
            self.status_label.setText("Select at least one rigid body")
            return

        if not selected_signals:
            self.status_label.setText("Select at least one signal")
            return

        self.position_plot_widget.clear()
        self.position_plot_widget.addLegend()

        self.rotation_plot_widget.clear()
        self.rotation_plot_widget.addLegend()

        time = self.session.time

        pos_curve_idx = 0
        rot_curve_idx = 0

        for body_name in selected_bodies:
            positions = self.get_active_positions(body_name)
            rotations = self.get_active_rotations(body_name)

            for signal_label in selected_signals:
                curve_name = f"{body_name} - {signal_label}"

                if signal_label in POSITION_SIGNAL_INDICES:
                    signal_index = POSITION_SIGNAL_INDICES[signal_label]
                    values = positions[:, signal_index]

                    curve_color = color_for_curve(pos_curve_idx)

                    self.position_plot_widget.plot(
                        time,
                        values,
                        pen=pg.mkPen(color=curve_color, width=2),
                        name=curve_name
                    )

                    pos_curve_idx += 1

                elif signal_label in ROTATION_SIGNAL_INDICES:
                    signal_index = ROTATION_SIGNAL_INDICES[signal_label]
                    values = rotations[:, signal_index]

                    curve_color = color_for_curve(rot_curve_idx)

                    self.rotation_plot_widget.plot(
                        time,
                        values,
                        pen=pg.mkPen(color=curve_color, width=2),
                        name=curve_name
                    )

                    rot_curve_idx += 1


        self.status_label.setText(
            f"Plotting {len(selected_bodies)} bodies and {len(selected_signals)} signals"
        )

        self.update_3d_view()

    def clear_3d_meshes(self) -> None:
        for mesh_item in self.mesh_items_by_body.values():
            self.view_3d_widget.removeItem(mesh_item)

        self.mesh_items_by_body.clear()
        self.base_vertices_by_body.clear()

    def handle_body_selection_changed(self) -> None:
        self.update_3d_view()

        if self.session is not None and self.selected_signal_labels():
            self.update_plot()

    def rebuild_body_geometry_cache(self) -> None:
        self.base_vertices_by_body.clear()

        for body_name, settings in self.body_display_settings.items():
            self.base_vertices_by_body[body_name] = create_body_vertices(
                shape=settings["shape"],
                length=settings["length"],
                width=settings["width"],
                height=settings["height"],
            )

    def update_3d_view(self) -> None:
        if self.session is None:
            return

        selected_bodies = self.selected_body_names()
        selected_body_set = set(selected_bodies)

        for body_name in list(self.mesh_items_by_body.keys()):
            if body_name not in selected_body_set:
                mesh_item = self.mesh_items_by_body.pop(body_name)
                self.view_3d_widget.removeItem(mesh_item)

        if not selected_bodies:
            self.time_label.setText(
                f"Time: {self.current_time_s:.3f} s | Frame: --"
            )
            return

        frame_idx = self.current_frame_idx

        for body_name in selected_bodies:
            self.update_body_mesh_for_frame(
                body_name=body_name,
                frame_idx=frame_idx,
            )

        sample_time_s = float(self.session.time[frame_idx])
        frame_number = int(self.session.frames[frame_idx])

        self.time_label.setText(
            f"Time: {self.current_time_s:.3f} s | "
            f"Sample: {sample_time_s:.3f} s | "
            f"Frame: {frame_number}"
        )

    def set_3d_time_from_slider(self, slider_time_ms: int) -> None:
        time_s = slider_time_ms / 1000.0

        self.set_3d_time(time_s, update_slider=False)

        if self.playback_timer.isActive():
            self.playback_start_wall_time_s = time.perf_counter()
            self.playback_start_data_time_s = self.current_time_s

    def play_3d(self) -> None:
        if self.session is None:
            self.status_label.setText("Load a CSV before playback")
            return
        
        self.playback_speed = self.playback_speed_spinbox.value()
        self.playback_start_wall_time_s = time.perf_counter()
        self.playback_start_data_time_s = self.current_time_s

        render_fps = int(self.render_fps_combobox.currentText())
        timer_interval_ms = int(round(1000.0 / render_fps))

        self.playback_timer.start(timer_interval_ms)

    def pause_3d(self) -> None:
        self.playback_timer.stop()

    def update_body_mesh_for_frame(
        self,
        body_name: str,
        frame_idx: int) -> None:
        positions = self.get_active_positions(body_name)
        rotations = self.get_active_rotations(body_name)

        position_display = positions[frame_idx]
        rotation_display = rotations[frame_idx]

        settings = self.body_display_settings[body_name]
        base_vertices = self.base_vertices_by_body[body_name]

        transformed_vertices = transform_body_vertices(
            base_vertices=base_vertices,
            position_transform=position_display,
            qx=rotation_display[0],
            qy=rotation_display[1],
            qz=rotation_display[2],
            qw=rotation_display[3],
        )

        if body_name not in self.mesh_items_by_body:
            mesh_item = make_body_mesh_item(
                vertices=transformed_vertices,
                color=settings["color"],
                shape=settings["shape"],
            )

            self.view_3d_widget.addItem(mesh_item)
            self.mesh_items_by_body[body_name] = mesh_item

        else:
            mesh_item = self.mesh_items_by_body[body_name]

            update_body_mesh_item(
                mesh_item=mesh_item,
                vertices=transformed_vertices,
                shape=settings["shape"],
            )

    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = speed

        if self.playback_timer.isActive():
            self.playback_start_wall_time_s = time.perf_counter()
            self.playback_start_data_time_s = self.current_time_s

    def set_render_fps_cap(self, fps_text: str) -> None:
        if not self.playback_timer.isActive():
            return

        render_fps = int(fps_text)
        timer_interval_ms = int(round(1000.0 / render_fps))

        self.playback_start_wall_time_s = time.perf_counter()
        self.playback_start_data_time_s = self.current_time_s

        self.playback_timer.start(timer_interval_ms)

    def advance_3d_time(self) -> None:
        if self.session is None:
            return

        duration_s = float(self.session.time[-1])

        if duration_s <= 0.0:
            return

        elapsed_wall_time_s = time.perf_counter() - self.playback_start_wall_time_s
        target_time_s = self.playback_start_data_time_s + elapsed_wall_time_s * self.playback_speed

        if target_time_s > duration_s:
            target_time_s = target_time_s % duration_s
            self.playback_start_wall_time_s = time.perf_counter()
            self.playback_start_data_time_s = target_time_s

        self.set_3d_time(target_time_s, update_slider=True)

    def frame_idx_from_time(self, time_s: float) -> int:
        if self.session is None:
            return 0

        times = self.session.time

        right_idx = int(np.searchsorted(times, time_s, side="left"))

        if right_idx <= 0:
            return 0

        if right_idx >= len(times):
            return len(times) - 1

        left_idx = right_idx - 1

        left_error = abs(time_s - times[left_idx])
        right_error = abs(times[right_idx] - time_s)

        if left_error <= right_error:
            return left_idx
        return right_idx

    def set_3d_time(self, time_s: float, update_slider: bool = True) -> None:
        if self.session is None:
            return

        duration_s = float(self.session.time[-1])

        if duration_s <= 0.0:
            self.current_time_s = 0.0
            self.current_frame_idx = 0
            return

        self.current_time_s = max(0.0, min(time_s, duration_s))
        self.current_frame_idx = self.frame_idx_from_time(self.current_time_s)

        if update_slider:
            slider_time_ms = int(round(self.current_time_s * 1000.0))

            self.time_slider.blockSignals(True)
            self.time_slider.setValue(slider_time_ms)
            self.time_slider.blockSignals(False)

        self.update_3d_view()

    def update_smoothed_tracking_data(self) -> None:
        if self.session is None:
            return

        smoothing_seconds = self.smoothing_seconds_spinbox.value()

        self.smoothed_display_positions.clear()
        self.smoothed_display_rotations.clear()

        for body_name in self.display_positions:
            positions = self.display_positions[body_name]
            rotations = self.display_rotations[body_name]

            smoothed_positions, smoothed_rotations = (
                smooth_tracking_positions_and_rotations(
                    time_s=self.session.time,
                    positions=positions,
                    rotations=rotations,
                    smoothing_seconds=smoothing_seconds
                )
            )

            self.smoothed_display_positions[body_name] = smoothed_positions
            self.smoothed_display_rotations[body_name] = smoothed_rotations

    def handle_smoothing_settings_changed(self) -> None:
        if self.session is None:
            return

        self.update_smoothed_tracking_data()
        self.update_3d_view()

        if self.selected_body_names() and self.selected_signal_labels():
            self.update_plot()

    def get_active_positions(self, body_name: str) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            return self.smoothed_display_positions[body_name]

        return self.display_positions[body_name]

    def get_active_rotations(self, body_name: str) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            return self.smoothed_display_rotations[body_name]

        return self.display_rotations[body_name]

    def create_export_settings_group(self) -> QGroupBox:
        export_group = QGroupBox("Video Export")
        export_layout = QVBoxLayout(export_group)

        export_layout.addWidget(QLabel("Export is not implemented yet."))

        self.export_resolution_combobox = QComboBox()
        self.export_resolution_combobox.addItems(PLAYBACK_RESOLUTION_OPTIONS)
        self.export_resolution_combobox.setCurrentText("Current widget size")

        export_layout.addWidget(QLabel("Export resolution"))
        export_layout.addWidget(self.export_resolution_combobox)

        self.export_fps_combobox = QComboBox()
        self.export_fps_combobox.addItems(["30", "60", "120"])
        self.export_fps_combobox.setCurrentText("60")

        export_layout.addWidget(QLabel("Export FPS"))
        export_layout.addWidget(self.export_fps_combobox)

        self.export_msaa_combobox = QComboBox()
        self.export_msaa_combobox.addItems(MSAA_OPTIONS)
        self.export_msaa_combobox.setCurrentText("4x")

        export_layout.addWidget(QLabel("Export MSAA"))
        export_layout.addWidget(self.export_msaa_combobox)

        self.export_ssaa_combobox = QComboBox()
        self.export_ssaa_combobox.addItems(SSAA_OPTIONS)
        self.export_ssaa_combobox.setCurrentText("2x")

        export_layout.addWidget(QLabel("Export SSAA"))
        export_layout.addWidget(self.export_ssaa_combobox)

        self.export_button = QPushButton("Export Video")
        self.export_button.setEnabled(False)
        export_layout.addWidget(self.export_button)

        export_group.setEnabled(False)

        return export_group

    def handle_playback_render_settings_changed(self) -> None:
        self.status_label.setText(
            "Playback render settings not implemented. "
            "MSAA is applied when the OpenGL context is created. "
            "SSAA and fixed playback resolution require the later offscreen renderer."
        )

def main() -> None:
    configure_default_opengl_format(DEFAULT_PLAYBACK_MSAA_SAMPLES)

    app = QApplication(sys.argv)

    window = PositionPlotterWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()