from __future__ import annotations

import importlib
import subprocess
import sys
import traceback
import threading


BASIC_DEPENDENCY_TESTS = {
    "numpy": ("numpy", "numpy"),
    "pandas": ("pandas", "pandas"),
    "PySide6": ("PySide6.QtCore", "PySide6"),
    "OpenGL": ("OpenGL", "PyOpenGL"),
}


def find_missing_dependencies() -> dict[str, tuple[str, str]]:
    missing_dependencies: dict[str, tuple[str, str]] = {}

    for dependency_name, (import_name, pip_name) in BASIC_DEPENDENCY_TESTS.items():
        try:
            importlib.import_module(import_name)
        except Exception as exc:
            missing_dependencies[dependency_name] = (
                pip_name,
                f"{type(exc).__name__}: {exc}",
            )

    if "PySide6" not in missing_dependencies:
        try:
            importlib.import_module("pyqtgraph")
        except Exception as exc:
            missing_dependencies["pyqtgraph"] = (
                "pyqtgraph",
                f"{type(exc).__name__}: {exc}",
            )

    if (
        "PySide6" not in missing_dependencies
        and "pyqtgraph" not in missing_dependencies
        and "OpenGL" not in missing_dependencies
    ):
        try:
            importlib.import_module("pyqtgraph.opengl")
        except Exception as exc:
            missing_dependencies["pyqtgraph.opengl"] = (
                "pyqtgraph",
                f"{type(exc).__name__}: {exc}",
            )

    return missing_dependencies


def show_message(title: str, message: str) -> None:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()

        if app is None:
            app = QApplication(sys.argv)

        QMessageBox.critical(None, title, message)
        return

    except Exception:
        pass

    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
        return

    except Exception:
        pass

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            title,
            0x10,
        )
        return

    except Exception:
        pass


def ask_yes_no(title: str, message: str) -> bool:
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        app = QApplication.instance()

        if app is None:
            app = QApplication(sys.argv)

        result = QMessageBox.question(
            None,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        return result == QMessageBox.StandardButton.Yes

    except Exception:
        pass

    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        result = messagebox.askyesno(title, message)
        root.destroy()

        return result

    except Exception:
        pass

    try:
        import ctypes

        result = ctypes.windll.user32.MessageBoxW(
            None,
            message,
            title,
            0x24,
        )

        return result == 6

    except Exception:
        pass

    return False


def install_dependencies(pip_package_names: list[str]) -> tuple[bool, str]:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        *pip_package_names,
    ]

    try:
        return install_dependencies_with_tk_progress(command)

    except Exception:
        return install_dependencies_without_progress(command)


def install_dependencies_without_progress(
        command: list[str]) -> tuple[bool, str]:
    show_message(
        "Installing Dependencies",
        "The program is installing the missing dependencies.\n\n"
        "This may take several minutes. Please wait until another message appears.",
    )

    try:
        completed_process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

    except Exception:
        return False, traceback.format_exc()

    output_text = completed_process.stdout + "\n" + completed_process.stderr

    if completed_process.returncode == 0:
        return True, output_text

    return False, output_text


def install_dependencies_with_tk_progress(
        command: list[str]) -> tuple[bool, str]:
    import tkinter
    from tkinter import ttk

    result: dict[str, object] = {
        "finished": False,
        "success": False,
        "output": "",
    }

    def run_install() -> None:
        try:
            completed_process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )

            output_text = (
                completed_process.stdout
                + "\n"
                + completed_process.stderr
            )

            result["success"] = completed_process.returncode == 0
            result["output"] = output_text

        except Exception:
            result["success"] = False
            result["output"] = traceback.format_exc()

        result["finished"] = True

    root = tkinter.Tk()
    root.title("Installing Dependencies")
    root.geometry("520x170")
    root.resizable(False, False)

    message_label = tkinter.Label(
        root,
        text=(
            "Installing missing Python dependencies...\n\n"
            "This may take several minutes. Please wait."
        ),
        justify="center",
    )
    message_label.pack(pady=(20, 10))

    progress_bar = ttk.Progressbar(
        root,
        mode="indeterminate",
        length=420,
    )
    progress_bar.pack(pady=10)
    progress_bar.start(10)

    command_label = tkinter.Label(
        root,
        text="Running: " + " ".join(command),
        wraplength=480,
        justify="center",
        font=("Segoe UI", 8),
    )
    command_label.pack(pady=(5, 10))

    install_thread = threading.Thread(
        target=run_install,
        daemon=True,
    )
    install_thread.start()

    def check_finished() -> None:
        if bool(result["finished"]):
            progress_bar.stop()
            root.destroy()
            return

        root.after(100, check_finished)

    root.after(100, check_finished)
    root.mainloop()

    return bool(result["success"]), str(result["output"])


def ensure_dependencies_or_exit() -> None:
    missing_dependencies = find_missing_dependencies()

    if not missing_dependencies:
        return

    missing_pip_names = list(
        dict.fromkeys(
            pip_name
            for pip_name, _ in missing_dependencies.values()
        )
    )

    missing_text = "\n".join(
        f"  - import {import_name}  |  pip package: {pip_name}\n"
        f"    error: {error_text}"
        for import_name, (pip_name, error_text)
        in missing_dependencies.items()
    )

    install_command_text = (
        f"{sys.executable} -m pip install --upgrade "
        + " ".join(missing_pip_names)
    )

    message = (
        "This program cannot start because required Python dependencies "
        "are missing or could not be imported.\n\n"
        "Python executable:\n"
        f"{sys.executable}\n\n"
        "Missing or broken dependencies:\n"
        f"{missing_text}\n\n"
        "Install command:\n"
        f"{install_command_text}\n\n"
        "Do you want to install or repair these dependencies now?"
    )

    should_install = ask_yes_no(
        "Missing Python Dependencies",
        message,
    )

    if not should_install:
        show_message(
            "Program Not Started",
            "The program will now close because required dependencies "
            "are missing or broken.",
        )
        sys.exit(1)

    success, install_output = install_dependencies(missing_pip_names)

    if not success:
        show_message(
            "Dependency Installation Failed",
            "The dependency installation failed.\n\n"
            "Output:\n"
            f"{install_output}",
        )
        sys.exit(1)

    missing_after_install = find_missing_dependencies()

    if missing_after_install:
        missing_after_text = "\n".join(
            f"  - import {import_name}  |  pip package: {pip_name}\n"
            f"    error: {error_text}"
            for import_name, (pip_name, error_text)
            in missing_after_install.items()
        )

        show_message(
            "Dependencies Still Missing",
            "Installation finished, but some dependencies still could not "
            "be imported.\n\n"
            f"{missing_after_text}",
        )
        sys.exit(1)

    show_message(
        "Dependencies Installed",
        "The missing dependencies were installed successfully.\n\n"
        "Please restart the program.",
    )

    sys.exit(0)