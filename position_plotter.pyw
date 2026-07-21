#%%

import sys

from motive_io import load_motive_rigid_body_csv, TrackingSession

from signal_processing import smooth_values

from PySide6.QtCore import Qt
from PySide6.QtWidgets import(
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget
)

import pyqtgraph as pg


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

class PositionPlotterWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OptiTrack Position Plotter")
        self.resize(1400, 800)

        self.session: TrackingSession | None = None
        self.body_checkboxes: dict[str, QCheckBox] = {}
        self.signal_checkboxes: dict[str, QCheckBox] = {}

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

        self.plot_tabs = QTabWidget()
        self.plot_tabs.addTab(self.position_plot_widget, "Position")
        self.plot_tabs.addTab(self.rotation_plot_widget, "Rotation")

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

        if apply_smoothing:
            smoothing_text = f"with {smoothing_window} frame smoothing"
        else:
            smoothing_text = ""


        self.status_label.setText(
            f"Plotting {len(selected_bodies)} bodies and {len(selected_signals)} signals"
        )

def main() -> None:
    app = QApplication(sys.argv)

    window = PositionPlotterWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()