from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys


REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "requirements.txt"
IMPORT_ALIASES = {
    "PySide6": "PySide6.QtCore",
    "vtk": "vtkmodules.vtkRenderingCore",
    "PyOpenGL": "OpenGL.GL",
    "pyzmq": "zmq",
}


def _requirements() -> list[str]:
    return [
        line.strip()
        for line in REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _python_executable() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        console_python = executable.with_name("python.exe")
        if console_python.exists():
            return str(console_python)
    return sys.executable


def _missing_dependencies() -> dict[str, str]:
    missing: dict[str, str] = {}
    for package in _requirements():
        module = IMPORT_ALIASES.get(package, package)
        try:
            importlib.import_module(module)
        except Exception as exc:
            missing[package] = f"{type(exc).__name__}: {exc}"
    return missing


def _dialog(title: str, message: str, question: bool = False) -> bool:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance() or QApplication(sys.argv)
        if question:
            result = QMessageBox.question(
                None,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return result == QMessageBox.StandardButton.Yes
        QMessageBox.critical(None, title, message)
        return True
    except Exception:
        pass

    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        result = messagebox.askyesno(title, message) if question else messagebox.showerror(title, message)
        root.destroy()
        return bool(result) if question else True
    except Exception:
        return False


def ensure_dependencies_or_exit() -> None:
    missing = _missing_dependencies()
    if not missing:
        return

    missing_text = "\n".join(f"- {name}: {error}" for name, error in missing.items())
    command = [_python_executable(), "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)]
    message = (
        "Some required packages are missing or broken:\n\n"
        f"{missing_text}\n\nInstall/repair them now?\n\n"
        + subprocess.list2cmdline(command)
    )
    if not _dialog("Missing Python Dependencies", message, question=True):
        sys.exit(1)

    creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    result = subprocess.run(command, check=False, creationflags=creationflags)
    if result.returncode != 0:
        _dialog("Dependency Installation Failed", "pip returned an error. The program will close.")
        sys.exit(1)

    _dialog("Dependencies Installed", "Dependencies were installed. Restart the program.")
    sys.exit(0)
