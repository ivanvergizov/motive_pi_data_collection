from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QGroupBox, QVBoxLayout


class BodySelectionWidget(QGroupBox):
    selection_changed = Signal()

    def __init__(self) -> None:
        super().__init__("Rigid bodies")
        self.setEnabled(False)
        self._layout = QVBoxLayout(self)
        self.checkboxes: dict[str, QCheckBox] = {}

    def set_bodies(self, body_names: list[str]) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.checkboxes.clear()
        for name in body_names:
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self.selection_changed)
            self.checkboxes[name] = checkbox
            self._layout.addWidget(checkbox)
        self.setEnabled(bool(body_names))

    def selected_names(self) -> list[str]:
        return [name for name, checkbox in self.checkboxes.items() if checkbox.isChecked()]
