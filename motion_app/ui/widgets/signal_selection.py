from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from motion_app.core.app_types import PlotSignalSelection
from motion_app.core.constants import SIGNAL_DEFINITIONS


class SignalSelectionWidget(QGroupBox):
    selections_changed = Signal()

    def __init__(self) -> None:
        super().__init__("Bodies and signals")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Rigid body and signal"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(280)
        self.tree.setEnabled(False)
        QVBoxLayout(self).addWidget(self.tree)

        self.body_items: dict[tuple[str, str], QTreeWidgetItem] = {}
        self.all_items: dict[str, QTreeWidgetItem] = {}
        self._updating = False
        self.tree.itemChanged.connect(self._handle_item_changed)

    def set_bodies(self, body_names: list[str]) -> None:
        self._updating = True
        self.tree.clear()
        self.body_items.clear()
        self.all_items.clear()

        all_bodies = QTreeWidgetItem(["All rigid bodies"])
        self.tree.addTopLevelItem(all_bodies)
        for signal in SIGNAL_DEFINITIONS:
            item = self._new_signal_item("all", signal)
            all_bodies.addChild(item)
            self.all_items[signal] = item

        for body_name in body_names:
            body_item = QTreeWidgetItem([body_name])
            self.tree.addTopLevelItem(body_item)
            for signal in SIGNAL_DEFINITIONS:
                item = self._new_signal_item(body_name, signal)
                body_item.addChild(item)
                self.body_items[(body_name, signal)] = item

        all_bodies.setExpanded(True)
        self.tree.setEnabled(bool(body_names))
        self._updating = False

    def selections(self) -> list[PlotSignalSelection]:
        return [
            PlotSignalSelection(body_name, signal)
            for (body_name, signal), item in self.body_items.items()
            if item.checkState(0) == Qt.CheckState.Checked
        ]

    def _new_signal_item(self, body_name: str, signal: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([signal])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Unchecked)
        item.setData(0, Qt.ItemDataRole.UserRole, (body_name, signal))
        return item

    def _handle_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is None:
            return

        body_name, signal = data
        self._updating = True
        if body_name == "all":
            state = item.checkState(0)
            for (name, item_signal), body_item in self.body_items.items():
                if item_signal == signal:
                    body_item.setCheckState(0, state)
        else:
            states = [
                body_item.checkState(0)
                for (name, item_signal), body_item in self.body_items.items()
                if item_signal == signal
            ]
            if all(state == Qt.CheckState.Checked for state in states):
                aggregate = Qt.CheckState.Checked
            elif all(state == Qt.CheckState.Unchecked for state in states):
                aggregate = Qt.CheckState.Unchecked
            else:
                aggregate = Qt.CheckState.PartiallyChecked
            self.all_items[signal].setCheckState(0, aggregate)

        self._updating = False
        self.selections_changed.emit()
