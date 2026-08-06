#%%

from __future__ import annotations

import sys
import time
from typing import TypedDict

from dependency_check import ensure_dependencies_or_exit

ensure_dependencies_or_exit()

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat, QVector3D
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
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
)

from motive_io import TrackingSession, load_motive_rigid_body_csv
from rigid_body_gl import (
    create_body_vertices,
    make_body_mesh_item,
    transform_body_vertices,
    update_body_mesh_item,
)
from rigid_body_math import (
    motive_positions_to_display,
    quaternions_xyzw_to_xyz_degrees,
)
from signal_processing import smooth_tracking_positions_and_rotations


POSITION_COMPONENT_INDICES = {
    "X": 0,
    "Y": 1,
    "Z": 2,
}

QUATERNION_COMPONENT_INDICES = {
    "X": 0,
    "Y": 1,
    "Z": 2,
    "W": 3,
}

XYZ_COMPONENT_INDICES = {
    "X": 0,
    "Y": 1,
    "Z": 2,
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
    "#890346",
]

DEFAULT_LIVE_MSAA_SAMPLES = 4

EXPORT_RESOLUTION_OPTIONS = [
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


def msaa_text_to_samples(msaa_text: str) -> int:
    normalized_text = msaa_text.strip().lower()

    if normalized_text == "off":
        return 0

    if normalized_text.endswith("x"):
        normalized_text = normalized_text[:-1]

    samples = int(normalized_text)

    if samples < 0:
        raise ValueError("MSAA samples cannot be negative.")

    return samples


def make_opengl_surface_format(msaa_samples: int) -> QSurfaceFormat:
    surface_format = QSurfaceFormat(QSurfaceFormat.defaultFormat())
    surface_format.setDepthBufferSize(24)
    surface_format.setStencilBufferSize(8)
    surface_format.setAlphaBufferSize(8)
    surface_format.setSamples(msaa_samples)
    return surface_format


def configure_default_opengl_format(msaa_samples: int) -> None:
    QSurfaceFormat.setDefaultFormat(make_opengl_surface_format(msaa_samples))


class BodyDisplaySettings(TypedDict):
    shape: str
    length: float
    width: float
    height: float
    color: str


class CameraState(TypedDict):
    center: tuple[float, float, float]
    distance: float
    elevation: float
    azimuth: float
    fov: float


class PositionPlotterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OptiTrack Position Plotter")
        self.resize(1400, 800)

        self.session: TrackingSession | None = None
        self.body_checkboxes: dict[str, QCheckBox] = {}
        self.position_component_checkboxes: dict[str, QCheckBox] = {}
        self.xyz_component_checkboxes: dict[str, QCheckBox] = {}
        self.quaternion_component_checkboxes: dict[str, QCheckBox] = {}

        self.display_positions: dict[str, np.ndarray] = {}
        self.rotation_quaternions: dict[str, np.ndarray] = {}
        self.rotation_xyz_degrees: dict[str, np.ndarray] = {}

        self.smoothed_display_positions: dict[str, np.ndarray] = {}
        self.smoothed_rotation_quaternions: dict[str, np.ndarray] = {}
        self.smoothed_rotation_xyz_degrees: dict[str, np.ndarray] = {}

        self.current_time_s = 0.0
        self.current_frame_idx = 0
        self.current_live_msaa_samples = DEFAULT_LIVE_MSAA_SAMPLES

        self.mesh_items_by_body: dict[str, gl.GLMeshItem] = {}
        self.base_vertices_by_body: dict[str, np.ndarray] = {}
        self.body_display_settings: dict[str, BodyDisplaySettings] = {}

        self.playback_speed = 1.0
        self.playback_start_wall_time_s = 0.0
        self.playback_start_data_time_s = 0.0

        self.playback_timer = QTimer(self)
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
        self.rotation_plot_widget.setLabel("left", "Quaternion component")
        self.rotation_plot_widget.addLegend()

        self.view_3d_widget = self.create_3d_view_widget(
            self.current_live_msaa_samples
        )
        self.grid_3d: gl.GLGridItem | None = None
        self.axis_3d: gl.GLAxisItem | None = None
        self.add_static_3d_scene_items()

        self.plot_tabs = QTabWidget()
        self.plot_tabs.addTab(self.position_plot_widget, "Position")
        self.plot_tabs.addTab(self.rotation_plot_widget, "Rotation")
        self.plot_tabs.addTab(self.view_3d_widget, "3D")

        self._build_layout()

    def create_3d_view_widget(self, msaa_samples: int) -> gl.GLViewWidget:
        view_widget = gl.GLViewWidget()
        view_widget.setFormat(make_opengl_surface_format(msaa_samples))
        view_widget.setBackgroundColor("w")
        view_widget.setCameraPosition(
            distance=2.0,
            elevation=25.0,
            azimuth=45.0,
        )
        return view_widget

    def add_static_3d_scene_items(self) -> None:
        self.grid_3d = gl.GLGridItem()
        self.grid_3d.setSize(x=2.0, y=2.0)
        self.grid_3d.setSpacing(x=0.1, y=0.1)
        self.grid_3d.setColor((0, 0, 0, 150))
        self.view_3d_widget.addItem(self.grid_3d)

        self.axis_3d = gl.GLAxisItem()
        self.axis_3d.setSize(x=0.4, y=0.4, z=0.4)
        self.view_3d_widget.addItem(self.axis_3d)

    def _build_layout(self) -> None:
        root = QWidget()
        main_layout = QHBoxLayout(root)

        settings_scroll_area = QScrollArea()
        settings_scroll_area.setWidgetResizable(True)
        settings_scroll_area.setMinimumWidth(340)

        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        settings_scroll_area.setWidget(settings_container)

        load_button = QPushButton("Load Motive CSV")
        load_button.clicked.connect(self.load_csv)

        plot_button = QPushButton("Update Plot")
        plot_button.clicked.connect(self.update_plot)

        settings_layout.addWidget(load_button)
        settings_layout.addWidget(plot_button)

        self.status_label = QLabel("No CSV loaded.")
        self.status_label.setWordWrap(True)
        settings_layout.addWidget(self.status_label)

        self.body_group = QGroupBox("Rigid bodies")
        self.body_layout = QVBoxLayout(self.body_group)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setWidget(self.body_group)
        settings_layout.addWidget(body_scroll)

        settings_layout.addWidget(self.create_position_signal_group())
        settings_layout.addWidget(self.create_rotation_signal_group())
        settings_layout.addWidget(self.create_smoothing_group())
        settings_layout.addWidget(self.create_playback_group())
        settings_layout.addWidget(self.create_export_settings_group())
        settings_layout.addStretch()

        main_layout.addWidget(settings_scroll_area)
        main_layout.addWidget(self.plot_tabs, stretch=1)
        self.setCentralWidget(root)

    def create_position_signal_group(self) -> QGroupBox:
        position_group = QGroupBox("Position plot signals")
        position_layout = QVBoxLayout(position_group)

        for component in POSITION_COMPONENT_INDICES:
            checkbox = QCheckBox(f"Position {component}")
            self.position_component_checkboxes[component] = checkbox
            position_layout.addWidget(checkbox)

        return position_group

    def create_rotation_signal_group(self) -> QGroupBox:
        rotation_group = QGroupBox("Rotation plot signals")
        rotation_layout = QVBoxLayout(rotation_group)

        self.rotation_mode_button_group = QButtonGroup(self)
        self.rotation_mode_button_group.setExclusive(True)

        self.xyz_rotation_mode_checkbox = QCheckBox("Plot XYZ rotation")
        self.quaternion_rotation_mode_checkbox = QCheckBox(
            "Plot quaternion rotation"
        )

        self.rotation_mode_button_group.addButton(self.xyz_rotation_mode_checkbox)
        self.rotation_mode_button_group.addButton(
            self.quaternion_rotation_mode_checkbox
        )
        self.quaternion_rotation_mode_checkbox.setChecked(True)

        self.xyz_rotation_mode_checkbox.toggled.connect(
            self.handle_rotation_plot_mode_changed
        )
        self.quaternion_rotation_mode_checkbox.toggled.connect(
            self.handle_rotation_plot_mode_changed
        )

        rotation_layout.addWidget(self.xyz_rotation_mode_checkbox)

        self.xyz_components_widget = QWidget()
        xyz_components_layout = QVBoxLayout(self.xyz_components_widget)
        xyz_components_layout.setContentsMargins(20, 0, 0, 0)

        for component in XYZ_COMPONENT_INDICES:
            checkbox = QCheckBox(f"Rotation {component}")
            self.xyz_component_checkboxes[component] = checkbox
            xyz_components_layout.addWidget(checkbox)

        rotation_layout.addWidget(self.xyz_components_widget)
        rotation_layout.addWidget(self.quaternion_rotation_mode_checkbox)

        self.quaternion_components_widget = QWidget()
        quaternion_components_layout = QVBoxLayout(
            self.quaternion_components_widget
        )
        quaternion_components_layout.setContentsMargins(20, 0, 0, 0)

        for component in QUATERNION_COMPONENT_INDICES:
            checkbox = QCheckBox(f"Rotation {component}")
            self.quaternion_component_checkboxes[component] = checkbox
            quaternion_components_layout.addWidget(checkbox)

        rotation_layout.addWidget(self.quaternion_components_widget)
        self.update_rotation_component_visibility()

        return rotation_group

    def create_smoothing_group(self) -> QGroupBox:
        smoothing_group = QGroupBox("Smoothing")
        smoothing_layout = QVBoxLayout(smoothing_group)

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

        return smoothing_group

    def create_playback_group(self) -> QGroupBox:
        playback_group = QGroupBox("3D Playback")
        playback_layout = QVBoxLayout(playback_group)

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
        self.render_fps_combobox.currentTextChanged.connect(
            self.set_render_fps_cap
        )

        self.live_msaa_combobox = QComboBox()
        self.live_msaa_combobox.addItems(MSAA_OPTIONS)
        self.live_msaa_combobox.setCurrentText("4x")
        self.live_msaa_combobox.currentTextChanged.connect(
            self.handle_live_msaa_changed
        )

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
        playback_layout.addWidget(QLabel("Live MSAA"))
        playback_layout.addWidget(self.live_msaa_combobox)
        playback_layout.addLayout(playback_button_layout)

        return playback_group

    def create_export_settings_group(self) -> QGroupBox:
        export_group = QGroupBox("Video Export")
        export_layout = QVBoxLayout(export_group)

        export_layout.addWidget(QLabel("Export is not implemented yet."))

        self.export_resolution_combobox = QComboBox()
        self.export_resolution_combobox.addItems(EXPORT_RESOLUTION_OPTIONS)
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

        self.pause_3d()
        self.populate_body_checkboxes()
        self.set_rotation_plot_mode(self.session.source_rotation_encoding)

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
        self.rotation_quaternions.clear()
        self.rotation_xyz_degrees.clear()

        for body_name, body in self.session.bodies.items():
            self.display_positions[body_name] = motive_positions_to_display(
                body.position_x,
                body.position_y,
                body.position_z,
            )
            self.rotation_quaternions[body_name] = (
                body.rotation_quaternion_xyzw.copy()
            )
            self.rotation_xyz_degrees[body_name] = (
                body.rotation_xyz_degrees.copy()
            )

        self.update_smoothed_tracking_data()

        duration_s = float(self.session.time[-1])
        duration_ms = max(0, int(round(duration_s * 1000.0)))

        self.time_slider.blockSignals(True)
        self.time_slider.setMaximum(duration_ms)
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)

        self.set_3d_time(0.0, update_slider=True)

        num_bodies = len(self.session.bodies)
        self.status_label.setText(
            f"Loaded {num_bodies} rigid bodies from a {duration_s:.3f} s "
            f"recording. Source rotation encoding: "
            f"{self.session.source_rotation_encoding}."
        )

    def set_rotation_plot_mode(self, rotation_encoding: str) -> None:
        if rotation_encoding == "XYZ":
            self.xyz_rotation_mode_checkbox.setChecked(True)
        else:
            self.quaternion_rotation_mode_checkbox.setChecked(True)

        self.update_rotation_component_visibility()

    def rotation_plot_mode(self) -> str:
        if self.xyz_rotation_mode_checkbox.isChecked():
            return "XYZ"

        return "Quaternion"

    def update_rotation_component_visibility(self) -> None:
        xyz_mode = self.rotation_plot_mode() == "XYZ"
        self.xyz_components_widget.setVisible(xyz_mode)
        self.quaternion_components_widget.setVisible(not xyz_mode)

        if xyz_mode:
            self.rotation_plot_widget.setLabel(
                "left",
                "XYZ rotation",
                units="deg",
            )
        else:
            self.rotation_plot_widget.setLabel(
                "left",
                "Quaternion component",
            )

    def handle_rotation_plot_mode_changed(self, checked: bool) -> None:
        if not checked:
            return

        self.update_rotation_component_visibility()

        if self.session is not None and self.selected_body_names():
            if self.has_selected_plot_signals():
                self.update_plot()

    def selected_body_names(self) -> list[str]:
        return [
            body_name
            for body_name, checkbox in self.body_checkboxes.items()
            if checkbox.isChecked()
        ]

    def selected_position_components(self) -> list[str]:
        return [
            component
            for component, checkbox in self.position_component_checkboxes.items()
            if checkbox.isChecked()
        ]

    def selected_rotation_components(self) -> list[str]:
        if self.rotation_plot_mode() == "XYZ":
            checkboxes = self.xyz_component_checkboxes
        else:
            checkboxes = self.quaternion_component_checkboxes

        return [
            component
            for component, checkbox in checkboxes.items()
            if checkbox.isChecked()
        ]

    def has_selected_plot_signals(self) -> bool:
        return bool(
            self.selected_position_components()
            or self.selected_rotation_components()
        )

    def update_plot(self) -> None:
        if self.session is None:
            self.status_label.setText("Load a CSV before plotting.")
            return

        selected_bodies = self.selected_body_names()
        selected_position_components = self.selected_position_components()
        selected_rotation_components = self.selected_rotation_components()

        if not selected_bodies:
            self.status_label.setText("Select at least one rigid body.")
            return

        if not selected_position_components and not selected_rotation_components:
            self.status_label.setText("Select at least one plot signal.")
            return

        self.position_plot_widget.clear()
        self.position_plot_widget.addLegend()
        self.rotation_plot_widget.clear()
        self.rotation_plot_widget.addLegend()

        time_s = self.session.time
        position_curve_index = 0
        rotation_curve_index = 0
        rotation_mode = self.rotation_plot_mode()

        for body_name in selected_bodies:
            positions = self.get_active_positions(body_name)

            for component in selected_position_components:
                signal_index = POSITION_COMPONENT_INDICES[component]
                curve_color = color_for_curve(position_curve_index)

                self.position_plot_widget.plot(
                    time_s,
                    positions[:, signal_index],
                    pen=pg.mkPen(color=curve_color, width=2),
                    name=f"{body_name} - Position {component}",
                )
                position_curve_index += 1

            if rotation_mode == "XYZ":
                rotations = self.get_active_xyz_degrees(body_name)
                component_indices = XYZ_COMPONENT_INDICES
                representation_name = "XYZ"
            else:
                rotations = self.get_active_quaternions(body_name)
                component_indices = QUATERNION_COMPONENT_INDICES
                representation_name = "Quaternion"

            for component in selected_rotation_components:
                signal_index = component_indices[component]
                curve_color = color_for_curve(rotation_curve_index)

                self.rotation_plot_widget.plot(
                    time_s,
                    rotations[:, signal_index],
                    pen=pg.mkPen(color=curve_color, width=2),
                    name=(
                        f"{body_name} - {representation_name} "
                        f"Rotation {component}"
                    ),
                )
                rotation_curve_index += 1

        total_signals = (
            len(selected_position_components) + len(selected_rotation_components)
        )
        self.status_label.setText(
            f"Plotting {len(selected_bodies)} bodies and "
            f"{total_signals} selected signals."
        )
        self.update_3d_view()

    def clear_3d_meshes(self) -> None:
        for mesh_item in self.mesh_items_by_body.values():
            self.view_3d_widget.removeItem(mesh_item)

        self.mesh_items_by_body.clear()
        self.base_vertices_by_body.clear()

    def handle_body_selection_changed(self, _state: int) -> None:
        self.update_3d_view()

        if self.session is not None and self.has_selected_plot_signals():
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

        for body_name in list(self.mesh_items_by_body):
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
            self.update_body_mesh_for_frame(body_name, frame_idx)

        sample_time_s = float(self.session.time[frame_idx])
        frame_number = int(self.session.frames[frame_idx])

        self.time_label.setText(
            f"Time: {self.current_time_s:.3f} s | "
            f"Sample: {sample_time_s:.3f} s | "
            f"Frame: {frame_number}"
        )

    def set_3d_time_from_slider(self, slider_time_ms: int) -> None:
        self.set_3d_time(slider_time_ms / 1000.0, update_slider=False)

        if self.playback_timer.isActive():
            self.playback_start_wall_time_s = time.perf_counter()
            self.playback_start_data_time_s = self.current_time_s

    def play_3d(self) -> None:
        if self.session is None:
            self.status_label.setText("Load a CSV before playback.")
            return

        self.playback_speed = self.playback_speed_spinbox.value()
        self.playback_start_wall_time_s = time.perf_counter()
        self.playback_start_data_time_s = self.current_time_s
        self.playback_timer.start(self.render_timer_interval_ms())

    def pause_3d(self) -> None:
        self.playback_timer.stop()

    def render_timer_interval_ms(self) -> int:
        render_fps = int(self.render_fps_combobox.currentText())
        return max(1, int(round(1000.0 / render_fps)))

    def update_body_mesh_for_frame(
        self,
        body_name: str,
        frame_idx: int,
    ) -> None:
        position_display = self.get_active_positions(body_name)[frame_idx]
        rotation_quaternion = self.get_active_quaternions(body_name)[frame_idx]

        settings = self.body_display_settings[body_name]
        base_vertices = self.base_vertices_by_body[body_name]

        transformed_vertices = transform_body_vertices(
            base_vertices=base_vertices,
            position_transform=position_display,
            qx=rotation_quaternion[0],
            qy=rotation_quaternion[1],
            qz=rotation_quaternion[2],
            qw=rotation_quaternion[3],
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
            update_body_mesh_item(
                mesh_item=self.mesh_items_by_body[body_name],
                vertices=transformed_vertices,
                shape=settings["shape"],
            )

    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = speed

        if self.playback_timer.isActive():
            self.playback_start_wall_time_s = time.perf_counter()
            self.playback_start_data_time_s = self.current_time_s

    def set_render_fps_cap(self, _fps_text: str) -> None:
        if not self.playback_timer.isActive():
            return

        self.playback_start_wall_time_s = time.perf_counter()
        self.playback_start_data_time_s = self.current_time_s
        self.playback_timer.start(self.render_timer_interval_ms())

    def advance_3d_time(self) -> None:
        if self.session is None:
            return

        duration_s = float(self.session.time[-1])

        if duration_s <= 0.0:
            return

        elapsed_wall_time_s = time.perf_counter() - self.playback_start_wall_time_s
        target_time_s = (
            self.playback_start_data_time_s
            + elapsed_wall_time_s * self.playback_speed
        )

        if target_time_s > duration_s:
            target_time_s %= duration_s
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
            self.update_3d_view()
            return

        self.current_time_s = max(0.0, min(float(time_s), duration_s))
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
        self.smoothed_rotation_quaternions.clear()
        self.smoothed_rotation_xyz_degrees.clear()

        for body_name in self.display_positions:
            smoothed_positions, smoothed_quaternions = (
                smooth_tracking_positions_and_rotations(
                    time_s=self.session.time,
                    positions=self.display_positions[body_name],
                    rotations=self.rotation_quaternions[body_name],
                    smoothing_seconds=smoothing_seconds,
                )
            )

            self.smoothed_display_positions[body_name] = smoothed_positions
            self.smoothed_rotation_quaternions[body_name] = smoothed_quaternions
            self.smoothed_rotation_xyz_degrees[body_name] = (
                quaternions_xyzw_to_xyz_degrees(smoothed_quaternions)
            )

    def handle_smoothing_settings_changed(self, _value: object) -> None:
        if self.session is None:
            return

        self.update_smoothed_tracking_data()
        self.update_3d_view()

        if self.selected_body_names() and self.has_selected_plot_signals():
            self.update_plot()

    def get_active_positions(self, body_name: str) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            return self.smoothed_display_positions[body_name]

        return self.display_positions[body_name]

    def get_active_quaternions(self, body_name: str) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            return self.smoothed_rotation_quaternions[body_name]

        return self.rotation_quaternions[body_name]

    def get_active_xyz_degrees(self, body_name: str) -> np.ndarray:
        if self.smoothing_checkbox.isChecked():
            return self.smoothed_rotation_xyz_degrees[body_name]

        return self.rotation_xyz_degrees[body_name]

    def capture_camera_state(self) -> CameraState:
        center = self.view_3d_widget.opts["center"]

        return {
            "center": (float(center.x()), float(center.y()), float(center.z())),
            "distance": float(self.view_3d_widget.opts["distance"]),
            "elevation": float(self.view_3d_widget.opts["elevation"]),
            "azimuth": float(self.view_3d_widget.opts["azimuth"]),
            "fov": float(self.view_3d_widget.opts["fov"]),
        }

    def restore_camera_state(self, camera_state: CameraState) -> None:
        center_x, center_y, center_z = camera_state["center"]
        self.view_3d_widget.opts["fov"] = camera_state["fov"]
        self.view_3d_widget.setCameraPosition(
            pos=QVector3D(center_x, center_y, center_z),
            distance=camera_state["distance"],
            elevation=camera_state["elevation"],
            azimuth=camera_state["azimuth"],
        )

    def handle_live_msaa_changed(self, msaa_text: str) -> None:
        requested_samples = msaa_text_to_samples(msaa_text)

        if requested_samples == self.current_live_msaa_samples:
            return

        self.rebuild_3d_tab_with_msaa(requested_samples)

    def rebuild_3d_tab_with_msaa(self, msaa_samples: int) -> None:
        was_playing = self.playback_timer.isActive()
        camera_state = self.capture_camera_state()
        current_tab_index = self.plot_tabs.currentIndex()
        old_3d_tab_index = self.plot_tabs.indexOf(self.view_3d_widget)
        old_view_widget = self.view_3d_widget

        self.pause_3d()

        self.plot_tabs.removeTab(old_3d_tab_index)
        old_view_widget.setParent(None)

        self.mesh_items_by_body.clear()
        self.base_vertices_by_body.clear()

        self.view_3d_widget = self.create_3d_view_widget(msaa_samples)
        self.current_live_msaa_samples = msaa_samples
        self.add_static_3d_scene_items()
        self.plot_tabs.insertTab(old_3d_tab_index, self.view_3d_widget, "3D")
        self.plot_tabs.setCurrentIndex(current_tab_index)

        old_view_widget.deleteLater()

        self.rebuild_body_geometry_cache()
        self.restore_camera_state(camera_state)
        self.update_3d_view()

        if was_playing:
            self.playback_start_wall_time_s = time.perf_counter()
            self.playback_start_data_time_s = self.current_time_s
            self.playback_timer.start(self.render_timer_interval_ms())

        msaa_label = "Off" if msaa_samples == 0 else f"{msaa_samples}x"
        self.status_label.setText(
            f"Recreated the 3D tab with requested live MSAA: {msaa_label}."
        )


def main() -> None:
    configure_default_opengl_format(DEFAULT_LIVE_MSAA_SAMPLES)

    app = QApplication(sys.argv)
    window = PositionPlotterWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
