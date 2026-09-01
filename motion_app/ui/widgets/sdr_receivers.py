from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from motion_app.live.testbed import SdrReceiverPlan


class SdrReceiversWidget(QGroupBox):
    """Editable table for the controller-side SDR receiver list."""

    def __init__(self) -> None:
        super().__init__("SDR receiver nodes")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Node", "Host", "ZMQ port"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(150)

        self.add_button = QPushButton("Add receiver")
        self.remove_button = QPushButton("Remove selected")
        self.add_button.clicked.connect(lambda _checked=False: self.add_receiver())
        self.remove_button.clicked.connect(self.remove_selected)

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def set_receivers(self, receivers: tuple[SdrReceiverPlan, ...]) -> None:
        self.table.setRowCount(0)
        for receiver in receivers:
            self.add_receiver(receiver.node, receiver.host, receiver.port)

    def add_receiver(
        self,
        node: int | None = None,
        host: str | None = None,
        port: int = 55555,
        _checked: bool | None = None,
    ) -> None:
        if node is None:
            existing = []
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                try:
                    existing.append(int(item.text()))
                except (AttributeError, ValueError):
                    pass
            node = max(existing, default=164) + 1
        if host is None:
            host = f"10.1.1.{node}"

        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, value in enumerate((node, host, port)):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignRight if column != 1 else Qt.AlignmentFlag.AlignLeft))
            self.table.setItem(row, column, item)

    def remove_selected(self, _checked: bool | None = None) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)

    def values(self) -> list[dict[str, object]]:
        values: list[dict[str, object]] = []
        for row in range(self.table.rowCount()):
            node_item = self.table.item(row, 0)
            host_item = self.table.item(row, 1)
            port_item = self.table.item(row, 2)
            if node_item is None or host_item is None or port_item is None:
                raise ValueError(f"SDR receiver row {row + 1} is incomplete")
            node_text = node_item.text().strip()
            host = host_item.text().strip()
            port_text = port_item.text().strip()
            if not node_text or not host or not port_text:
                raise ValueError(f"SDR receiver row {row + 1} must include node, host, and port")
            try:
                node = int(node_text)
                port = int(port_text)
            except ValueError as exc:
                raise ValueError(f"SDR receiver row {row + 1} node and port must be integers") from exc
            values.append({"node": node, "host": host, "port": port})
        return values
