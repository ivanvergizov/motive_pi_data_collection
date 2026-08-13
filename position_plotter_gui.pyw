from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_API", "pyside6")

from motion_app.support.dependency_check import ensure_dependencies_or_exit

ensure_dependencies_or_exit()

from PySide6.QtWidgets import QApplication

from motion_app.ui.main_window import WorkspaceMainWindow


def main() -> None:
    app = QApplication(sys.argv)
    window = WorkspaceMainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
