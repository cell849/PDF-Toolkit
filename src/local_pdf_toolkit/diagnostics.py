"""Offline packaging self-test, including the spawned worker in frozen builds."""

import tempfile
from pathlib import Path

import pymupdf
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.core.jobs import JobController


def self_test():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    registry = build_registry()
    status = [1]
    with tempfile.TemporaryDirectory(prefix="pdf-toolkit-selftest-") as folder:
        root = Path(folder)
        # Exercise the actual widgets and bundled artwork, not just Core/worker imports.
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root / "preferences")
        )
        from local_pdf_toolkit.ui.icons import resource_path
        from local_pdf_toolkit.ui.main_window import MainWindow

        window = MainWindow(registry)
        window._select_tool(
            next(
                i for i, spec in enumerate(window._operations) if spec.operation_id == "pdf.to_jpeg"
            )
        )
        window.show()
        app.processEvents()
        rendered = window.grab()
        artwork = QPixmap(str(resource_path("chevron-light.svg")))
        valid_ui = (
            not rendered.isNull() and not window.windowIcon().isNull() and not artwork.isNull()
        )
        window.close()
        app.processEvents()
        if not valid_ui:
            return 1
        source = root / "fixture.pdf"
        with pymupdf.open() as doc:
            doc.new_page(width=72, height=72).insert_text((5, 30), "Test")
            doc.save(source)
        jobs = JobController()

        def finished(paths, error):
            if error is None and len(paths) == 1:
                image = pymupdf.Pixmap(str(paths[0]))
                status[0] = 0 if (image.width, image.height) == (150, 150) else 1
            app.quit()

        jobs.finished.connect(finished)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(jobs.cancel)
        timeout.start(30000)
        jobs.start(registry.get("pdf.to_jpeg"), source, root, {})
        app.exec()
        timeout.stop()
    return status[0]
