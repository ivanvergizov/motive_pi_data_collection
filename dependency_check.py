from __future__ import annotations

import importlib
from pathlib import Path
import subprocess
import sys
import traceback


DEPENDENCY_IMPORT_TESTS = {
    "numpy": "numpy",
    "pandas": "pandas",
    "PySide6": "PySide6.QtCore",
    "pyqtgraph": "pyqtgraph",
    "pyqtgraph.opengl": "pyqtgraph.opengl",
    "OpenGL": "OpenGL",
}


PIP_PACKAGES_TO_INSTALL = [
    "numpy",
    "pandas",
    "pyqtgraph",
    "PyOpenGL",
    "PySide6",
    "PySide6_Addons",
    "PySide6_Essentials",
    "shiboken6",
]


def get_console_python_executable() -> str:
    executable_path = Path(sys.executable)

    if executable_path.name.lower() == "pythonw.exe":
        python_exe_path = executable_path.with_name("python.exe")

        if python_exe_path.exists():
            return str(python_exe_path)

    return sys.executable


def find_failed_imports() -> dict[str, str]:
    failed_imports: dict[str, str] = {}

    for dependency_name, import_name in DEPENDENCY_IMPORT_TESTS.items():
        try:
            importlib.import_module(import_name)

        except Exception as exc:
            failed_imports[dependency_name] = (
                f"{type(exc).__name__}: {exc}"
            )

    return failed_imports


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


def install_all_dependencies_in_command_window() -> tuple[bool, str]:
    python_executable = get_console_python_executable()

    pip_command = [
        python_executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        *PIP_PACKAGES_TO_INSTALL,
    ]

    command_text = subprocess.list2cmdline(pip_command)

    batch_command = (
        "echo Installing Python dependencies... && "
        "echo. && "
        f"{command_text} && "
        "set INSTALL_RESULT=0 || "
        "set INSTALL_RESULT=1 && "
        "echo. && "
        "echo Installation command finished. && "
        "echo Close this window or press any key to continue. && "
        "pause >nul && "
        "exit /b %INSTALL_RESULT%"
    )

    try:
        completed_process = subprocess.run(
            ["cmd.exe", "/C", batch_command],
            check=False,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )

    except Exception:
        return False, traceback.format_exc()

    if completed_process.returncode == 0:
        return True, "Dependency installation command completed successfully."

    return False, (
        "Dependency installation command failed. "
        "Check the command window output for details."
    )


def ensure_dependencies_or_exit() -> None:
    failed_imports = find_failed_imports()

    if not failed_imports:
        return

    failed_text = "\n".join(
        f"  - import {dependency_name}\n"
        f"    error: {error_text}"
        for dependency_name, error_text in failed_imports.items()
    )

    python_executable = get_console_python_executable()

    install_command_text = (
        f"{python_executable} -m pip install --upgrade "
        + " ".join(PIP_PACKAGES_TO_INSTALL)
    )

    message = (
        "This program cannot start because one or more required Python dependencies could not be imported.\n\n"
        "Python executable:\n"
        f"{python_executable}\n\n"
        "Failed imports:\n"
        f"{failed_text}\n\n"
        "The program can open a command window and run this install command:\n"
        f"{install_command_text}\n\n"
        "Do you want to install or repair these dependencies now?"
    )

    should_install = ask_yes_no(
        "Missing or Broken Python Dependencies",
        message,
    )

    if not should_install:
        show_message(
            "Program Not Started",
            "The program will now close because required dependencies are missing or broken.",
        )
        sys.exit(1)

    success, install_output = install_all_dependencies_in_command_window()

    if not success:
        show_message(
            "Dependency Installation Failed",
            "The dependency installation command failed.\n\n"
            f"{install_output}",
        )
        sys.exit(1)

    failed_after_install = find_failed_imports_in_fresh_process()

    if failed_after_install:
        failed_after_text = "\n".join(
            f"  - import {dependency_name}\n"
            f"    error: {error_text}"
            for dependency_name, error_text in failed_after_install.items()
        )

        show_message(
            "Dependencies Still Broken",
            "Installation finished, but some dependencies still could not be imported.\n\n"
            f"{failed_after_text}",
        )
        sys.exit(1)

    show_message(
        "Dependencies Installed",
        "The dependencies were installed successfully.\n\n"
        "Please restart the program.",
    )

    sys.exit(0)

def find_failed_imports_in_fresh_process() -> dict[str, str]:
    python_executable = get_console_python_executable()

    test_code_lines = [
        "import importlib",
        "failed_imports = {}",
    ]

    for dependency_name, import_name in DEPENDENCY_IMPORT_TESTS.items():
        test_code_lines.extend(
            [
                "try:",
                f"    importlib.import_module({import_name!r})",
                "except Exception as exc:",
                f"    failed_imports[{dependency_name!r}] = f'{{type(exc).__name__}}: {{exc}}'",
            ]
        )

    test_code_lines.extend(
        [
            "if failed_imports:",
            "    for dependency_name, error_text in failed_imports.items():",
            "        print(f'{dependency_name}: {error_text}')",
            "    raise SystemExit(1)",
            "raise SystemExit(0)",
        ]
    )

    test_code = "\n".join(test_code_lines)

    try:
        completed_process = subprocess.run(
            [
                python_executable,
                "-c",
                test_code,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    except Exception:
        return {
            "external verification": traceback.format_exc()
        }

    if completed_process.returncode == 0:
        return {}

    failed_imports: dict[str, str] = {}

    output_text = completed_process.stdout + "\n" + completed_process.stderr

    for line in output_text.splitlines():
        if ": " in line:
            dependency_name, error_text = line.split(": ", 1)
            failed_imports[dependency_name] = error_text

    if not failed_imports:
        failed_imports["external verification"] = output_text.strip()

    return failed_imports