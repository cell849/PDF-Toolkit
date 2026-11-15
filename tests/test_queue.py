from PySide6.QtCore import QEventLoop, QTimer

from local_pdf_toolkit.converters.images import ImagesPdfConverter
from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.registry import ConverterRegistry
from local_pdf_toolkit.ui.main_window import MainWindow


def finish(window, start):
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: loop.quit() if not window._active else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    start()
    timer.start()
    # Metadata inspection adds real spawned processes; hosted Windows cold starts vary.
    timeout.start(30000)
    loop.exec()
    timer.stop()
    timeout.stop()
    assert not window._active, (
        f"conversion={window.jobs.running}, inspection={window._probe_jobs.running}, "
        f"preview={window.document_preview.running}, deferred={window._requested_start}, "
        f"pending={len(window._pending)}"
    )


def test_batch_isolates_error_and_retries(qapp, fixture_dir, tmp_path):
    registry = ConverterRegistry()
    registry.register(PdfImagesConverter(FileFormat.PNG))
    window = MainWindow(registry)
    bad = tmp_path / "bad.pdf"
    bad.write_text("broken")
    window.add_paths([bad, fixture_dir / "one_page.pdf"])
    window.destination.setText(str(tmp_path))
    try:
        finish(window, window._start)
        assert window._failed == {0}
        assert window.files.item(1).text().startswith("Done")
        bad.write_bytes((fixture_dir / "one_page.pdf").read_bytes())
        finish(window, window._retry)
        assert not window._failed
        assert (tmp_path / "bad_page-0001.png").exists()
        assert window.files.item(1).text().startswith("Done")
    finally:
        window.close()


def test_order_controls_and_multi_input_job(qapp, tmp_path):
    import pymupdf
    from PIL import Image

    registry = ConverterRegistry()
    registry.register(ImagesPdfConverter())
    window = MainWindow(registry)
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (100, 200), "red").save(a)
    Image.new("RGB", (200, 100), "blue").save(b)
    window.add_paths([a, b])
    window.files.setCurrentRow(1)
    window._move(-1)
    assert window._paths == [b, a]
    window.destination.setText(str(tmp_path))
    try:
        finish(window, window._start)
        assert all(window.files.item(i).text().startswith("Done") for i in (0, 1))
        with pymupdf.open(tmp_path / "b_images.pdf") as doc:
            assert len(doc) == 2
            assert doc[0].rect.width > doc[0].rect.height
    finally:
        window.close()


def test_cancel_queued_job_does_not_cancel_other_files(qapp, fixture_dir, tmp_path):
    registry = ConverterRegistry()
    registry.register(PdfImagesConverter(FileFormat.PNG))
    window = MainWindow(registry)
    inputs = []
    for name in ("a", "b", "c"):
        path = tmp_path / f"{name}.pdf"
        path.write_bytes((fixture_dir / "one_page.pdf").read_bytes())
        inputs.append(path)
    window.add_paths(inputs)
    window.destination.setText(str(tmp_path))

    def start():
        window._start()
        window.files.setCurrentRow(1)
        window._cancel_one()

    try:
        finish(window, start)
        assert window._failed == {1}
        assert (tmp_path / "a_page-0001.png").exists()
        assert not (tmp_path / "b_page-0001.png").exists()
        assert (tmp_path / "c_page-0001.png").exists()
    finally:
        window.close()
