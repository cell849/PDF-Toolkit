"""Offline packaging self-test, including the spawned worker in frozen builds."""

import tempfile
from pathlib import Path

import pymupdf
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel

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
        from local_pdf_toolkit.ui.design import apply_theme
        from local_pdf_toolkit.ui.icons import resource_path
        from local_pdf_toolkit.ui.main_window import MainWindow

        window = MainWindow(registry)
        window.show()
        app.processEvents()
        valid_library = window.home_views.currentIndex() == 0 and all(
            button.isVisible() for button in window.category_buttons.values()
        )
        # The full grid is now intentionally behind Browse all tools.
        window._browse_tools("All tools")
        for dark in (False, True):
            apply_theme(window, dark)
            for _ in range(8):
                app.processEvents()
            for card in window.library.cards:
                valid_library &= card.isVisible() and card.height() >= 164
                for text in card.findChildren(QLabel):
                    valid_library &= (
                        text.isVisible()
                        and text.height() >= text.heightForWidth(text.width())
                        and card.rect().contains(text.geometry())
                    )
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
            valid_library
            and not rendered.isNull()
            and not window.windowIcon().isNull()
            and not artwork.isNull()
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
