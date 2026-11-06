from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout


class PlaybackControlsWidget(QGroupBox):
    seek_requested = Signal(float)
    play_requested = Signal()
    pause_requested = Signal()
    speed_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__("3D playback")
        self.setEnabled(False)
        self.time_label = QLabel("Time: 0.000 s | Frame: 0")
        self.time_slider = QSlider(Qt.Orientation.Horizontal)
        self.time_slider.setRange(0, 0)
        self.speed_spinbox = QDoubleSpinBox()
        self.speed_spinbox.setRange(0.25, 5.0)
        self.speed_spinbox.setSingleStep(0.25)
        self.speed_spinbox.setDecimals(2)
        self.speed_spinbox.setValue(1.0)
        self.speed_spinbox.setPrefix("Speed: ")
        self.speed_spinbox.setSuffix("x")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")

        buttons = QHBoxLayout()
        buttons.addWidget(self.play_button)
        buttons.addWidget(self.pause_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.time_label)
        layout.addWidget(self.time_slider)
        layout.addWidget(self.speed_spinbox)
        layout.addLayout(buttons)

        self.time_slider.valueChanged.connect(lambda ms: self.seek_requested.emit(ms / 1000.0))
        self.play_button.clicked.connect(self.play_requested)
        self.pause_button.clicked.connect(self.pause_requested)
        self.speed_spinbox.valueChanged.connect(self.speed_changed)

    def set_duration(self, duration_s: float, enabled: bool) -> None:
        self.time_slider.blockSignals(True)
        self.time_slider.setRange(0, int(round(max(duration_s, 0.0) * 1000.0)))
        self.time_slider.setValue(0)
        self.time_slider.blockSignals(False)
        self.setEnabled(enabled)

    def set_time(self, current_time_s: float, sample_time_s: float, frame_number: int) -> None:
        self.time_slider.blockSignals(True)
        self.time_slider.setValue(int(round(current_time_s * 1000.0)))
        self.time_slider.blockSignals(False)
        self.time_label.setText(
            f"Time: {current_time_s:.3f} s | Sample: {sample_time_s:.3f} s | Frame: {frame_number}"
        )
