from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGroupBox, QVBoxLayout


class SmoothingControlsWidget(QGroupBox):
    settings_changed = Signal(bool, float)

    def __init__(self, title: str, checkbox_text: str = "Apply smoothing") -> None:
        super().__init__(title)
        self.checkbox = QCheckBox(checkbox_text)
        self.seconds_spinbox = QDoubleSpinBox()
        self.seconds_spinbox.setRange(0.0, 5.0)
        self.seconds_spinbox.setSingleStep(0.05)
        self.seconds_spinbox.setDecimals(2)
        self.seconds_spinbox.setValue(0.25)
        self.seconds_spinbox.setPrefix("Window: ")
        self.seconds_spinbox.setSuffix(" s")
        self.seconds_spinbox.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.checkbox)
        layout.addWidget(self.seconds_spinbox)

        self.checkbox.stateChanged.connect(self._emit_settings)
        self.seconds_spinbox.valueChanged.connect(self._emit_settings)

    @property
    def enabled(self) -> bool:
        return self.checkbox.isChecked()

    @property
    def seconds(self) -> float:
        return float(self.seconds_spinbox.value())

    def set_available(self, available: bool) -> None:
        """Enable or disable the smoothing control as one coherent UI unit."""
        self.setEnabled(available)
        self.seconds_spinbox.setEnabled(available and self.checkbox.isChecked())

    def _emit_settings(self, _value: int | float | None = None) -> None:
        self.seconds_spinbox.setEnabled(self.checkbox.isEnabled() and self.checkbox.isChecked())
        self.settings_changed.emit(self.enabled, self.seconds)
