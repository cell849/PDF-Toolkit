"""Opt-in Windows Start menu shortcut for the portable executable."""

import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtWidgets import QMessageBox

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$programs = [Environment]::GetFolderPath('Programs')
if (-not $programs -or -not (Test-Path -LiteralPath $programs -PathType Container)) {
    throw 'The Start menu folder could not be found.'
}
$destination = Join-Path $programs 'PDF Toolkit.lnk'
if (Test-Path -LiteralPath $destination) {
    exit 2
}
$temporary = Join-Path $programs ('.pdf-toolkit-' + [guid]::NewGuid().ToString('N') + '.lnk')
try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($temporary)
    $shortcut.TargetPath = $env:PDF_TOOLKIT_SHORTCUT_TARGET
    $shortcut.WorkingDirectory = [IO.Path]::GetDirectoryName($env:PDF_TOOLKIT_SHORTCUT_TARGET)
    $shortcut.Description = 'PDF Toolkit'
    $shortcut.Save()
    [IO.File]::Move($temporary, $destination)
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
}
"""


def available():
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def add_shortcut(window):
    if not available() or getattr(window, "_start_menu_process", None) is not None:
        return
    process = QProcess(window)
    timeout = QTimer(process)
    timeout.setSingleShot(True)
    timeout.timeout.connect(process.kill)
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PDF_TOOLKIT_SHORTCUT_TARGET", sys.executable)
    process.setProcessEnvironment(environment)
    window._start_menu_process = process
    window.start_menu_action.setEnabled(False)

    def finish(success, detail=""):
        if window._start_menu_process is not process:
            return
        timeout.stop()
        window._start_menu_process = None
        window.start_menu_action.setEnabled(True)
        if success:
            QMessageBox.information(
                window,
                "Start menu shortcut",
                "PDF Toolkit was added to your Start menu. Windows may take a moment to list it. "
                "If you move the app folder, delete the old shortcut before adding it again.",
            )
        else:
            QMessageBox.warning(
                window,
                "Could not create shortcut",
                detail or "Windows could not create the shortcut.",
            )
        process.deleteLater()

    def completed(code, status):
        error = (
            "A PDF Toolkit shortcut already exists in your Start menu. "
            "Delete it before adding a new one."
            if code == 2
            else ""
        )
        finish(status == QProcess.ExitStatus.NormalExit and code == 0, error)

    process.finished.connect(completed)
    process.errorOccurred.connect(lambda _: finish(False))
    process.start(
        "powershell.exe",
        ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _SCRIPT],
    )
    timeout.start(15000)
