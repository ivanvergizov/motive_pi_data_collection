from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QGroupBox, QLabel, QPushButton, QVBoxLayout


class SessionSourceWidget(QGroupBox):
    file_selected = Signal(str)

    def __init__(self, title: str = "Data source", button_text: str = "Load Motive CSV") -> None:
        super().__init__(title)
        self.load_button = QPushButton(button_text)
        self.status_label = QLabel("No CSV loaded.")
        self.status_label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.load_button)
        layout.addWidget(self.status_label)
        self.load_button.clicked.connect(self._select_file)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _select_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Motive CSV", "", "CSV files (*.csv);;All files (*)")
        if file_path:
            self.file_selected.emit(file_path)
