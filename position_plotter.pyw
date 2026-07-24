#%%

import sys

from motive_io import load_motive_rigid_body_csv, TrackingSession

from signal_processing import smooth_values

from PySide6.QtCore import Qt, QTimer
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget
)

import pyqtgraph as pg
import pyqtgraph.opengl as gl

from rigid_body_gl import create_body_vertices, make_body_mesh_item, transform_body_vertices
from rigid_body_math import motive_positions_to_display

import numpy as np

from typing import TypedDict

import time


POSITION_SIGNALS = {
    "Position X": "position_x",
    "Position Y": "position_y",
    "Position Z": "position_z"
}

ROTATION_SIGNALS = {
    "Rotation X": "rotation_x",
    "Rotation Y": "rotation_y",
    "Rotation Z": "rotation_z",
    "Rotation W": "rotation_w",
}

SIGNALS = {
    **POSITION_SIGNALS,
    **ROTATION_SIGNALS
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

def color_for_curve(curve_index: int) -> str:
    return PLOT_COLORS[curve_index % len(PLOT_COLORS)]

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
        self.current_time_s = 0.0
        self.current_frame_idx = 0
        self.mesh_items: list[gl.GLMeshItem] = []

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

        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        load_button = QPushButton("Load Motive CSV")
        load_button.clicked.connect(self.load_csv)

        plot_button = QPushButton("Update Plot")
        plot_button.clicked.connect(self.update_plot)

        controls_layout.addWidget(load_button)
        controls_layout.addWidget(plot_button)

        self.status_label = QLabel("No CSV loaded.")
        controls_layout.addWidget(self.status_label)

        self.body_group = QGroupBox("Rigid bodies")
        self.body_layout = QVBoxLayout()
        self.body_group.setLayout(self.body_layout)

        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setWidget(self.body_group)

        controls_layout.addWidget(body_scroll)

        signal_group = QGroupBox("Signals")
        signal_layout = QVBoxLayout()

        for label in SIGNALS:
            checkbox = QCheckBox(label)

            self.signal_checkboxes[label] = checkbox
            signal_layout.addWidget(checkbox)

        signal_group.setLayout(signal_layout)
        controls_layout.addWidget(signal_group)

        smoothing_group = QGroupBox("Smoothing")
        smoothing_layout = QVBoxLayout()

        self.smoothing_checkbox = QCheckBox("Apply smoothing")
        smoothing_layout.addWidget(self.smoothing_checkbox)

        self.smoothing_window_spinbox = QSpinBox()
        self.smoothing_window_spinbox.setMinimum(1)
        self.smoothing_window_spinbox.setMaximum(501)
        self.smoothing_window_spinbox.setSingleStep(2)
        self.smoothing_window_spinbox.setPrefix("Window: ")
        self.smoothing_window_spinbox.setSuffix(" frames")

        smoothing_layout.addWidget(self.smoothing_window_spinbox)

        smoothing_group.setLayout(smoothing_layout)
        controls_layout.addWidget(smoothing_group)

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
        playback_layout.addLayout(playback_button_layout)

        playback_group.setLayout(playback_layout)
        controls_layout.addWidget(playback_group)

        controls_panel = QWidget()
        controls_panel.setLayout(controls_layout)
        controls_panel.setFixedWidth(320)

        main_layout.addWidget(controls_panel)
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

        self.display_positions.clear()

        for body_name, body in self.session.bodies.items():
            self.display_positions[body_name] = motive_positions_to_display(
                body.position_x,
                body.position_y,
                body.position_z
            )

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

        apply_smoothing = self.smoothing_checkbox.isChecked()
        smoothing_window = self.smoothing_window_spinbox.value()

        pos_curve_idx = 0
        rot_curve_idx = 0

        for body_name in selected_bodies:
            body = self.session.bodies[body_name]

            for signal_label in selected_signals:
                attribute_name = SIGNALS[signal_label]
                values = getattr(body, attribute_name)

                if apply_smoothing:
                    values = smooth_values(values, smoothing_window)

                curve_name = f"{body_name} - {signal_label}"

                if signal_label in POSITION_SIGNALS:
                    
                    curve_color = color_for_curve(pos_curve_idx)

                    self.position_plot_widget.plot(
                        time,
                        values,
                        pen=pg.mkPen(color=curve_color, width=2),
                        name=curve_name
                )
                    pos_curve_idx += 1
                    
                elif signal_label in ROTATION_SIGNALS:
                    
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
        for mesh_item in self.mesh_items:
            self.view_3d_widget.removeItem(mesh_item)
            
        self.mesh_items.clear()

    def update_3d_view(self) -> None:
        if self.session is None:
            return
        
        selected_bodies = self.selected_body_names()

        if not selected_bodies:
            self.clear_3d_meshes()
            return
        
        self.clear_3d_meshes()

        frame_idx = self.current_frame_idx

        for body_name in selected_bodies:
            body = self.session.bodies[body_name]

            position_display = self.display_positions[body_name][frame_idx]

            settings = self.body_display_settings[body_name]

            base_vertices = create_body_vertices(
                shape=settings["shape"],
                length=settings["length"],
                width=settings["width"],
                height=settings["height"]
            )

            body_color = str(settings["color"])

            transformed_vertices = transform_body_vertices(
                base_vertices=base_vertices,
                position_transform=position_display,
                qx=body.rotation_x[frame_idx],
                qy=body.rotation_y[frame_idx],
                qz=body.rotation_z[frame_idx],
                qw=body.rotation_w[frame_idx],
            )

            mesh_item = make_body_mesh_item(
                vertices=transformed_vertices,
                color=body_color,
                shape=settings["shape"]
            )

            self.view_3d_widget.addItem(mesh_item)
            self.mesh_items.append(mesh_item)

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

def main() -> None:
    app = QApplication(sys.argv)

    window = PositionPlotterWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()