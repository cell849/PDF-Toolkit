"""Application version and license information."""

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

_REPOSITORY = "https://github.com/cell849/PDF-Toolkit"


def _document_url(source_path: str, bundled_name: str) -> QUrl:
    if getattr(sys, "frozen", False):
        path = Path(sys.executable).resolve().parent / bundled_name
    else:
        path = Path(__file__).resolve().parents[3] / source_path
    if path.is_file():
        return QUrl.fromLocalFile(str(path))
    return QUrl(f"{_REPOSITORY}/blob/main/{source_path}")


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PDF Toolkit")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("PDF Toolkit")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        version = QCoreApplication.applicationVersion() or "Unknown"
        self.version_label = QLabel(f"Version {version}")
        layout.addWidget(self.version_label)
        layout.addWidget(QLabel("Project license: GNU GPL version 3.0"))

        for label, url in (
            ("Project license", _document_url("LICENSE", "LICENSE.txt")),
            ("Third-party notices", _document_url("packaging/THIRD_PARTY.md", "THIRD_PARTY.md")),
            ("Releases on GitHub", QUrl(f"{_REPOSITORY}/releases")),
        ):
            button = QPushButton(label)
            button.clicked.connect(
                lambda checked=False, target=url: QDesktopServices.openUrl(target)
            )
            layout.addWidget(button)

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)


def show_about(window):
    dialog = getattr(window, "_about_dialog", None)
    if dialog is None:
        dialog = AboutDialog(window)
        window._about_dialog = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
