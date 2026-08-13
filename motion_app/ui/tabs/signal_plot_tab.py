from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel,
    QScrollArea, QVBoxLayout, QWidget,
)

from motion_app.core.app_types import CurveSpec, SignalDataType, SignalMode
from motion_app.core.constants import SIGNAL_DEFINITIONS, color_for_curve
from motion_app.core.motive_io import TrackingSession, load_motive_rigid_body_csv
from motion_app.ui.plotting.multi_axis_signal_plot import MultiAxisSignalPlot
from motion_app.core.tracking_data import TrackingDataProvider
from motion_app.ui.widgets.session_source import SessionSourceWidget
from motion_app.ui.widgets.signal_selection import SignalSelectionWidget
from motion_app.ui.widgets.smoothing_controls import SmoothingControlsWidget


class SignalPlotTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.session: TrackingSession | None = None
        self.source_file_path: str | None = None
        self.data = TrackingDataProvider()

        self.source_widget = SessionSourceWidget()
        self.selection_widget = SignalSelectionWidget()
        self.smoothing = SmoothingControlsWidget("Plot smoothing")
        self.smoothing.set_available(False)
        self.raw_checkbox = QCheckBox("Plot values before interpolation")
        self.raw_checkbox.setEnabled(False)
        self.raw_checkbox.setToolTip(
            "Displays original samples with gaps where Motive data was missing. Raw mode takes precedence over smoothing."
        )
        self.plot = MultiAxisSignalPlot()
        self.axis_scale_spinboxes: dict[SignalDataType, QDoubleSpinBox] = {}

        self._build_layout()
        self._connect_signals()

    def _build_layout(self) -> None:
        settings = QWidget()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        settings_layout.addWidget(self.source_widget)
        settings_layout.addWidget(self.selection_widget)
        settings_layout.addWidget(self.smoothing)

        options = QGroupBox("Plot options")
        QVBoxLayout(options).addWidget(self.raw_checkbox)
        settings_layout.addWidget(options)
        settings_layout.addWidget(self._create_axis_scale_group())
        settings_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(340)
        scroll.setWidget(settings)

        layout = QHBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(self.plot, stretch=1)

    def _create_axis_scale_group(self) -> QGroupBox:
        group = QGroupBox("Vertical scaling")
        layout = QVBoxLayout(group)
        for label, data_type in (
            ("Position scale", "position"),
            ("Euler scale", "euler"),
            ("Quaternion scale", "quaternion"),
        ):
            row = QHBoxLayout()
            spinbox = QDoubleSpinBox()
            spinbox.setRange(0.10, 100.0)
            spinbox.setSingleStep(0.10)
            spinbox.setDecimals(2)
            spinbox.setValue(1.0)
            spinbox.setSuffix("x")
            spinbox.setKeyboardTracking(False)
            spinbox.setEnabled(False)
            spinbox.valueChanged.connect(lambda value, dt=data_type: self.plot.set_axis_scale(dt, value))
            self.axis_scale_spinboxes[data_type] = spinbox
            row.addWidget(QLabel(label), stretch=1)
            row.addWidget(spinbox)
            layout.addLayout(row)
        return group

    def _connect_signals(self) -> None:
        self.source_widget.file_selected.connect(self.load_csv)
        self.selection_widget.selections_changed.connect(self.update_plot)
        self.smoothing.settings_changed.connect(self._handle_smoothing_changed)
        self.raw_checkbox.stateChanged.connect(self._handle_mode_changed)

    def load_csv(self, file_path: str) -> None:
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
        self.selection_widget.set_bodies(list(session.bodies))
        self.raw_checkbox.setEnabled(True)
        self._update_smoothing_state()
        if len(session.time):
            self.plot.set_x_range(float(session.time[0]), float(session.time[-1]))
        self._update_status()
        self.update_plot()

    def _mode(self) -> SignalMode:
        if self.raw_checkbox.isChecked():
            return "raw"
        if self.smoothing.enabled:
            return "smoothed"
        return "interpolated"

    def _handle_smoothing_changed(self, _enabled: bool, _seconds: float) -> None:
        if self.raw_checkbox.isChecked():
            return
        self.update_plot()

    def _handle_mode_changed(self, _state: int) -> None:
        self._update_smoothing_state()
        self.update_plot()

    def _update_smoothing_state(self) -> None:
        loaded = self.session is not None
        raw = self.raw_checkbox.isChecked()
        self.smoothing.set_available(loaded and not raw)

    def update_plot(self) -> None:
        session = self.session
        if session is None:
            return
        specs: list[CurveSpec] = []
        mode = self._mode()
        for curve_index, selection in enumerate(self.selection_widget.selections()):
            data_type, _ = SIGNAL_DEFINITIONS[selection.signal_label]
            values = self.data.signal_values(
                selection.body_name,
                selection.signal_label,
                mode,
                self.smoothing.seconds,
            )
            specs.append(CurveSpec(
                data_type=data_type,
                name=f"{selection.body_name} - {selection.signal_label}",
                color=color_for_curve(curve_index),
                x=session.time,
                y=values,
            ))
        self.plot.set_curves(specs)
        for data_type, spinbox in self.axis_scale_spinboxes.items():
            spinbox.setEnabled(self.plot.has_data(data_type))

    def _update_status(self) -> None:
        session = self.session
        if session is None:
            self.source_widget.set_status("No CSV loaded.")
            return
        duration = float(session.time[-1]) if len(session.time) else 0.0
        source = self.source_file_path or "Session supplied externally"
        self.source_widget.set_status(
            f"{source}\n{len(session.bodies)} rigid bodies | {duration:.3f} s | source rotation: {session.source_rotation_encoding}"
        )
