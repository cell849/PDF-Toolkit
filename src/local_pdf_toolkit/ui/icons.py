"""Original document/checkmark artwork and explicit bundled-resource resolution."""

from pathlib import Path

from PySide6.QtGui import QIcon


def resource_path(name="app.svg"):
    """Resolve package data both in source checkouts and PyInstaller bundles."""
    return Path(__file__).resolve().parent / "assets" / "icons" / name


def app_icon():
    return QIcon(str(resource_path("app.ico")))
