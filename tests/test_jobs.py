from PySide6.QtCore import QEventLoop, QTimer

from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.jobs import JobController
from local_pdf_toolkit.core.registry import ConverterRegistry
from local_pdf_toolkit.ui.main_window import MainWindow


def wait_job(qapp, controller, start):
    loop = QEventLoop()
    results = []
    heartbeats = []
    pulse = QTimer()
    pulse.setInterval(5)
    pulse.timeout.connect(lambda: heartbeats.append(1))
    pulse.start()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(15000)

    def finished(paths, error):
        results.append((paths, error))
        loop.quit()

    controller.finished.connect(finished)
    start()
    loop.exec()
    timeout.stop()
    pulse.stop()
    if controller.running:
        controller.cancel()
        cleanup = QEventLoop()
        controller.finished.connect(cleanup.quit)
        QTimer.singleShot(10000, cleanup.quit)
        cleanup.exec()
    assert not controller.running
    assert results, "Worker did not complete within 15 seconds"
    assert heartbeats, "Qt event loop did not run during conversion"
    return results[0]


def test_spawned_process_converts_without_blocking_ui(qapp, fixture_dir, tmp_path):
    jobs = JobController()
    paths, error = wait_job(
        qapp,
        jobs,
        lambda: jobs.start(
            PdfImagesConverter(FileFormat.JPEG), fixture_dir / "one_page.pdf", tmp_path, {}
        ),
    )
    assert error is None
    assert len(paths) == 1 and paths[0].exists()


def test_spawned_process_cancellation(qapp, fixture_dir, tmp_path):
    jobs = JobController()

    def start():
        jobs.start(PdfImagesConverter(FileFormat.PNG), fixture_dir / "one_page.pdf", tmp_path, {})
        jobs.cancel()

    paths, error = wait_job(qapp, jobs, start)
    assert error[0] == "cancelled"
    assert not paths
    assert not list(tmp_path.iterdir())


def test_window_converts_imported_file(qapp, fixture_dir, tmp_path):
    registry = ConverterRegistry()
    registry.register(PdfImagesConverter(FileFormat.PNG))
    window = MainWindow(registry)
    window.add_paths([fixture_dir / "one_page.pdf"])
    window.destination.setText(str(tmp_path))
    try:
        paths, error = wait_job(qapp, window.jobs, window._start)
        qapp.processEvents()
        assert error is None
        assert len(paths) == 1
        assert window.files.item(0).text().startswith("Done")
    finally:
        window.close()
        qapp.processEvents()


def test_worker_reports_bad_input_then_accepts_next_job(qapp, fixture_dir, tmp_path):
    jobs = JobController()
    converter = PdfImagesConverter(FileFormat.PNG)
    bad = tmp_path / "bad.pdf"
    bad.write_text("not a PDF")
    paths, error = wait_job(qapp, jobs, lambda: jobs.start(converter, bad, tmp_path, {}))
    assert error[0] == "invalid_input"
    assert not paths
    paths, error = wait_job(
        qapp, jobs, lambda: jobs.start(converter, fixture_dir / "one_page.pdf", tmp_path, {})
    )
    assert error is None and len(paths) == 1


def test_window_accepts_local_file_drop(qapp, fixture_dir):
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent

    window = MainWindow(ConverterRegistry())
    mime = QMimeData()
    path = fixture_dir / "one_page.pdf"
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    drag = QDragEnterEvent(QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dragEnterEvent(drag)
    assert drag.isAccepted()
    drop = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(drop)
    assert window._paths == [path]
    window.close()


def test_close_during_conversion_cancels_and_waits(qapp, fixture_dir, tmp_path):
    registry = ConverterRegistry()
    registry.register(PdfImagesConverter(FileFormat.PNG))
    window = MainWindow(registry)
    window.add_paths([fixture_dir / "one_page.pdf"])
    window.destination.setText(str(tmp_path))
    window.show()

    def start_and_close():
        window._start()
        window.close()
        assert window._closing

    paths, error = wait_job(qapp, window.jobs, start_and_close)
    qapp.processEvents()
    assert error[0] == "cancelled"
    assert not paths
    assert not window.isVisible()
    assert not list(tmp_path.iterdir())


def test_windows_pipe_end_still_completes_job(qapp):
    jobs = JobController()

    class EndedPipe:
        def poll(self):
            raise BrokenPipeError(109, "The pipe has been ended")

        def close(self):
            pass

    class FinishedProcess:
        def is_alive(self):
            return False

        def join(self):
            pass

        def close(self):
            pass

    jobs._receiver = EndedPipe()
    jobs._process = FinishedProcess()
    jobs._result = ("completed.png",)
    jobs._error = None
    observed = []
    jobs.finished.connect(lambda paths, error: observed.append((paths, error)))
    jobs._poll()
    assert observed == [(("completed.png",), None)]
    assert not jobs.running
