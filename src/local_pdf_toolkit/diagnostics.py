"""Offline packaging self-test, including the spawned worker in frozen builds."""

import tempfile
from pathlib import Path

import pymupdf
from PySide6.QtCore import QCoreApplication, QTimer

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.core.jobs import JobController


def self_test():
    app = QCoreApplication([])
    registry = build_registry()
    status = [1]
    with tempfile.TemporaryDirectory(prefix="pdf-toolkit-selftest-") as folder:
        root = Path(folder)
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
