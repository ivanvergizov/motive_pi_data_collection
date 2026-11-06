from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGroupBox, QLabel, QVBoxLayout

from motion_app.core.constants import EXPORT_MSAA_OPTIONS, EXPORT_RESOLUTION_OPTIONS, SSAA_OPTIONS


class RenderSettingsWidget(QGroupBox):
    def __init__(
        self,
        title: str,
        note_text: str | None = None,
        include_resolution: bool = False,
        include_msaa: bool = False,
        include_ssaa: bool = False,
    ) -> None:
        super().__init__(title)
        self.resolution_combobox: QComboBox | None = None
        self.msaa_combobox: QComboBox | None = None
        self.ssaa_combobox: QComboBox | None = None

        layout = QVBoxLayout(self)

        if include_resolution:
            self.resolution_combobox = QComboBox()
            self.resolution_combobox.addItems(EXPORT_RESOLUTION_OPTIONS)
            self.resolution_combobox.setCurrentText("1920 x 1080")
            layout.addWidget(QLabel("Output resolution"))
            layout.addWidget(self.resolution_combobox)

        self.fps_combobox = QComboBox()
        self.fps_combobox.addItems(["15", "30", "60", "120"])
        self.fps_combobox.setCurrentText("30")
        layout.addWidget(QLabel("Frame rate"))
        layout.addWidget(self.fps_combobox)

        if include_msaa:
            self.msaa_combobox = QComboBox()
            self.msaa_combobox.addItems(EXPORT_MSAA_OPTIONS)
            self.msaa_combobox.setCurrentText("4x")
            layout.addWidget(QLabel("MSAA"))
            layout.addWidget(self.msaa_combobox)

        if include_ssaa:
            self.ssaa_combobox = QComboBox()
            self.ssaa_combobox.addItems(SSAA_OPTIONS)
            self.ssaa_combobox.setCurrentText("1x")
            layout.addWidget(QLabel("SSAA render scale"))
            layout.addWidget(self.ssaa_combobox)

        if note_text:
            note = QLabel(note_text)
            note.setWordWrap(True)
            layout.addWidget(note)

    def fps(self) -> int:
        return int(self.fps_combobox.currentText())

    def msaa_samples(self) -> int:
        if self.msaa_combobox is None:
            return 0
        text = self.msaa_combobox.currentText()
        return 0 if text == "Off" else int(text.removesuffix("x"))

    def ssaa_factor(self) -> int:
        return 1 if self.ssaa_combobox is None else int(self.ssaa_combobox.currentText().removesuffix("x"))

    def resolution(self) -> tuple[int, int] | None:
        if self.resolution_combobox is None:
            return None
        width, height = (
            int(part.strip())
            for part in self.resolution_combobox.currentText().lower().split("x", 1)
        )
        return width, height
