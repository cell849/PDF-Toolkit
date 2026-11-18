from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QPushButton

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow


def test_about_menu_shows_runtime_version_and_opens_local_notices(qapp, monkeypatch):
    from local_pdf_toolkit.ui import about

    opened = []
    monkeypatch.setattr(about.QDesktopServices, "openUrl", lambda url: opened.append(url))
    previous_version = QCoreApplication.applicationVersion()
    QCoreApplication.setApplicationVersion("9.8.7")
    window = MainWindow(build_registry())
    try:
        window.about_action.trigger()
        dialog = window._about_dialog
        assert dialog.isVisible()
        assert dialog.version_label.text() == "Version 9.8.7"
        assert not opened
        buttons = {button.text(): button for button in dialog.findChildren(QPushButton)}
        buttons["Project license"].click()
        buttons["Third-party notices"].click()
        buttons["Releases on GitHub"].click()
        assert opened[0].isLocalFile() and opened[0].toLocalFile().endswith("LICENSE")
        assert opened[1].isLocalFile() and opened[1].toLocalFile().endswith("THIRD_PARTY.md")
        assert opened[2].toString().endswith("/releases")
        window.about_action.trigger()
        assert window._about_dialog is dialog
    finally:
        window.close()
        QCoreApplication.setApplicationVersion(previous_version)


def test_packaged_about_finds_license_next_to_executable(tmp_path, monkeypatch):
    from local_pdf_toolkit.ui import about

    (tmp_path / "LICENSE.txt").write_text("license")
    monkeypatch.setattr(about.sys, "frozen", True, raising=False)
    monkeypatch.setattr(about.sys, "executable", str(tmp_path / "PDFToolkit.exe"))
    assert Path(about._document_url("LICENSE", "LICENSE.txt").toLocalFile()) == (
        tmp_path / "LICENSE.txt"
    )
