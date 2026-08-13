from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from motion_app.core.app_types import WorkspaceType
from motion_app.core.constants import DEFAULT_PREVIEW_AA, PREVIEW_AA_OPTIONS
from motion_app.ui.tabs.export_tab import ExportTab
from motion_app.ui.tabs.live_tab import LivePlaybackTab
from motion_app.ui.tabs.recorded_3d_tab import Recorded3DPlaybackTab
from motion_app.ui.tabs.signal_plot_tab import SignalPlotTab


class WorkspaceMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("OptiTrack Motion Workspace")
        self.resize(1500, 900)
        self.global_anti_aliasing = DEFAULT_PREVIEW_AA
        self.workspace_counts: dict[WorkspaceType, int] = {
            "signals": 0,
            "recorded_3d": 0,
            "live": 0,
            "export": 0,
        }

        self.workspace_tabs = QTabWidget()
        self.workspace_tabs.setTabsClosable(True)
        self.workspace_tabs.setMovable(True)
        self.workspace_tabs.setDocumentMode(True)
        self.workspace_tabs.tabCloseRequested.connect(self.close_workspace_tab)
        self.workspace_tabs.currentChanged.connect(
            lambda _index: QTimer.singleShot(250, self.verify_global_anti_aliasing)
        )
        self.setCentralWidget(self.workspace_tabs)
        self._create_toolbar()
        self.create_workspace("signals")

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Workspaces")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        new_tab_button = QToolButton()
        new_tab_button.setText("New tab")
        new_tab_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(new_tab_button)
        for title, workspace_type in (
            ("Signals plot", "signals"),
            ("Recorded 3D playback", "recorded_3d"),
            ("Live playback", "live"),
            ("Video export", "export"),
        ):
            action = menu.addAction(title)
            action.triggered.connect(partial(self.create_workspace, workspace_type))
        new_tab_button.setMenu(menu)
        toolbar.addWidget(new_tab_button)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Preview AA"))
        self.global_aa_combobox = QComboBox()
        self.global_aa_combobox.addItems(PREVIEW_AA_OPTIONS)
        self.global_aa_combobox.setCurrentText(self.global_anti_aliasing)
        self.global_aa_combobox.currentTextChanged.connect(self.handle_global_aa_changed)
        toolbar.addWidget(self.global_aa_combobox)
        self.global_aa_status_label = QLabel(f"Requested {self.global_anti_aliasing}; actual pending")
        self.global_aa_status_label.setMinimumWidth(260)
        toolbar.addWidget(self.global_aa_status_label)

        toolbar.addSeparator()
        close_button = QPushButton("Close current tab")
        close_button.clicked.connect(self.close_current_workspace)
        toolbar.addWidget(close_button)

    def create_workspace(self, workspace_type: WorkspaceType, _checked: bool | None = None) -> None:
        self.workspace_counts[workspace_type] += 1
        number = self.workspace_counts[workspace_type]

        if workspace_type == "signals":
            workspace: QWidget = SignalPlotTab()
            base_title = "Signals"
        elif workspace_type == "recorded_3d":
            workspace = Recorded3DPlaybackTab(self.global_anti_aliasing)
            base_title = "Recorded 3D"
        elif workspace_type == "live":
            workspace = LivePlaybackTab(self.global_anti_aliasing)
            base_title = "Live"
        elif workspace_type == "export":
            workspace = ExportTab(self.global_anti_aliasing)
            base_title = "Export"
        else:
            raise ValueError(f"Unsupported workspace type: {workspace_type!r}")

        index = self.workspace_tabs.addTab(workspace, f"{base_title} {number}")
        self.workspace_tabs.setCurrentIndex(index)
        QTimer.singleShot(250, self.verify_global_anti_aliasing)

    def handle_global_aa_changed(self, anti_aliasing: str) -> None:
        self.global_anti_aliasing = anti_aliasing
        self.global_aa_status_label.setText(f"Applying {anti_aliasing}; actual pending")
        for index in range(self.workspace_tabs.count()):
            workspace = self.workspace_tabs.widget(index)
            if isinstance(workspace, (Recorded3DPlaybackTab, LivePlaybackTab, ExportTab)):
                workspace.set_global_anti_aliasing(anti_aliasing)
        QTimer.singleShot(250, self.verify_global_anti_aliasing)

    def verify_global_anti_aliasing(self) -> None:
        actual_values: list[str] = []
        previews = 0
        for index in range(self.workspace_tabs.count()):
            workspace = self.workspace_tabs.widget(index)
            if not isinstance(workspace, (Recorded3DPlaybackTab, LivePlaybackTab, ExportTab)):
                continue
            previews += 1
            actual_values.append(workspace.scene.actual_anti_aliasing_text())

        if previews == 0:
            self.global_aa_status_label.setText(
                f"Requested {self.global_anti_aliasing}; no 3D preview open"
            )
            return

        actual_text = ", ".join(sorted(set(actual_values))) if actual_values else "pending"
        self.global_aa_status_label.setText(
            f"Requested {self.global_anti_aliasing}; actual {actual_text}"
        )

    def close_current_workspace(self) -> None:
        index = self.workspace_tabs.currentIndex()
        if index >= 0:
            self.close_workspace_tab(index)

    def close_workspace_tab(self, tab_index: int) -> None:
        workspace = self.workspace_tabs.widget(tab_index)
        if workspace is None:
            return
        self.workspace_tabs.removeTab(tab_index)
        self._shutdown_workspace(workspace)
        workspace.deleteLater()

    @staticmethod
    def _shutdown_workspace(workspace: QWidget) -> None:
        shutdown = getattr(workspace, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def closeEvent(self, event: QCloseEvent) -> None:
        for index in range(self.workspace_tabs.count() - 1, -1, -1):
            workspace = self.workspace_tabs.widget(index)
            if workspace is not None:
                self._shutdown_workspace(workspace)
        super().closeEvent(event)
