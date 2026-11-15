from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel

from local_pdf_toolkit.core.registry import ConverterRegistry
from local_pdf_toolkit.ui.main_window import MainWindow


def test_foundation_window_opens_and_closes_with_event_loop(qapp):
    window = MainWindow(ConverterRegistry())
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == "Local PDF Toolkit"
    assert any("No conversion tools" in label.text() for label in window.findChildren(QLabel))
    QTimer.singleShot(50, window.close)
    QTimer.singleShot(2000, qapp.quit)  # Prevent a regression from hanging CI.
    assert qapp.exec() == 0
    assert not window.isVisible()
    window.deleteLater()
    qapp.processEvents()
