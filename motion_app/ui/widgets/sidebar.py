from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QScrollArea, QSizePolicy, QWidget


def configure_sidebar(
    scroll: QScrollArea,
    content: QWidget,
    *,
    fixed_width: int | None = None,
    minimum_width: int | None = None,
    maximum_width: int | None = None,
) -> None:
    """Apply the shared sidebar sizing and text-wrapping behavior."""
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    if fixed_width is not None:
        scroll.setFixedWidth(fixed_width)
    else:
        if minimum_width is not None:
            scroll.setMinimumWidth(minimum_width)
        if maximum_width is not None:
            scroll.setMaximumWidth(maximum_width)

    content.setMinimumWidth(0)
    for label in content.findChildren(QLabel):
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )

    scroll.setWidget(content)
