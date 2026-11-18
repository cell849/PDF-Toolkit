"""Opt-in Windows shortcuts for the portable executable."""

import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer
from PySide6.QtWidgets import QMessageBox

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$kind = $env:PDF_TOOLKIT_SHORTCUT_LOCATION
if ($kind -eq 'start_menu') { $folder = [Environment]::GetFolderPath('Programs') }
elseif ($kind -eq 'desktop') { $folder = [Environment]::GetFolderPath('DesktopDirectory') }
else { throw 'Unsupported shortcut location.' }
if (-not $folder -or -not (Test-Path -LiteralPath $folder -PathType Container)) {
    throw 'The shortcut folder could not be found.'
}
$destination = Join-Path $folder 'PDF Toolkit.lnk'
if (Test-Path -LiteralPath $destination) {
    exit 2
}
$temporary = Join-Path $folder ('.pdf-toolkit-' + [guid]::NewGuid().ToString('N') + '.lnk')
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


def add_shortcut(window, location):
    if location not in ("start_menu", "desktop"):
        raise ValueError("Unsupported shortcut location")
    if not available() or getattr(window, "_shortcut_process", None) is not None:
        return
    location_name = "Start menu" if location == "start_menu" else "Desktop"
    process = QProcess(window)
    timeout = QTimer(process)
    timeout.setSingleShot(True)
    timeout.timeout.connect(process.kill)
    environment = QProcessEnvironment.systemEnvironment()
    environment.insert("PDF_TOOLKIT_SHORTCUT_TARGET", sys.executable)
    environment.insert("PDF_TOOLKIT_SHORTCUT_LOCATION", location)
    process.setProcessEnvironment(environment)
    window._shortcut_process = process
    actions = (window.start_menu_action, window.desktop_shortcut_action)
    for action in actions:
        action.setEnabled(False)

    def finish(success, detail=""):
        if window._shortcut_process is not process:
            return
        timeout.stop()
        window._shortcut_process = None
        for action in actions:
            action.setEnabled(True)
        if success:
            indexing = " Windows may take a moment to list it." if location == "start_menu" else ""
            QMessageBox.information(
                window,
                f"{location_name} shortcut",
                f"PDF Toolkit was added to your {location_name}.{indexing} "
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
        place = "in your Start menu" if location == "start_menu" else "on your Desktop"
        error = (
            f"A PDF Toolkit shortcut already exists {place}. Delete it before adding a new one."
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
