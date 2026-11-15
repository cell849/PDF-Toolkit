import json
import time
import wave
from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtTest import QTest

from local_pdf_toolkit.converters.file_probe import FileProbeConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.ui.document_preview import DocumentPreview


def probe(path, folder, **options):
    (result,) = FileProbeConverter().convert(
        path, folder, options, lambda _: None, CancellationToken()
    )
    data = json.loads(result.read_text())
    result.unlink()
    return data


def test_probe_detects_content_and_preserves_source(tmp_path):
    source = tmp_path / "misnamed.docx"
    with pymupdf.open() as document:
        document.new_page(width=72, height=144)
        document.save(source)
    before = source.read_bytes()
    data = probe(source, tmp_path)
    assert data["format"] == "pdf" and data["ready"]
    assert (data["pages"], data["width"], data["height"], data["unit"]) == (1, 72, 144, "pt")
    assert data["bytes"] == len(before) and source.read_bytes() == before
    assert not probe(source, tmp_path, formats="png,jpeg")["ready"]
    image = tmp_path / "misnamed.pdf"
    Image.new("RGB", (30, 20)).save(image, format="PNG")
    data = probe(image, tmp_path)
    assert data["format"] == "png" and data["ready"]
    assert (data["width"], data["height"], data["unit"]) == (30, 20, "px")
    media_named_image = tmp_path / "picture.mp3"
    image.rename(media_named_image)
    assert probe(media_named_image, tmp_path)["format"] == "png"


def test_probe_office_validates_content_without_launching_engine(tmp_path, monkeypatch):
    from docx import Document

    import local_pdf_toolkit.converters.office_pdf as office

    def forbidden(*args, **kwargs):
        pytest.fail("Inspection must never launch LibreOffice")

    monkeypatch.setattr(office, "_run", forbidden)
    source = tmp_path / "renamed.pdf"
    document = Document()
    document.core_properties.author = "Private author"
    document.add_paragraph("Private visible text")
    document.save(source)
    data = probe(source, tmp_path)
    assert data["format"] == "docx" and data["ready"]
    assert "Private" not in json.dumps(data)
    assert type(data["dependencies"]["libreoffice"]) is bool


def test_probe_encrypted_corrupt_and_binary_text_are_not_ready(tmp_path):
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(
            encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
    data = probe(encrypted, tmp_path)
    assert not data["ready"] and data["error_code"] == "password_required"
    corrupt = tmp_path / "broken.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nnot a valid document")
    assert not probe(corrupt, tmp_path)["ready"]
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"bad\x00binary")
    assert not probe(binary, tmp_path)["ready"]


def test_media_probe_uses_bounded_parser_and_rejects_fake_container(tmp_path):
    from local_pdf_toolkit.converters.media_metadata import find_ffmpeg

    if find_ffmpeg() is None:
        pytest.skip("FFprobe is separately installed")
    source = tmp_path / "private.wav"
    with wave.open(str(source), "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(b"\0\0" * 800)
    data = probe(source, tmp_path)
    assert data["ready"] and data["format"] == "wav"
    assert "private" not in json.dumps(data)
    source.write_bytes(b"fake media")
    assert not probe(source, tmp_path)["ready"]


class FakeJobs(QObject):
    finished = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.started = []
        self.cancelled = 0

    def start(self, converter, path, folder, options):
        assert not self.running
        self.running = True
        self.started.append((path, folder, options))

    def cancel(self):
        self.cancelled += 1

    def complete(self, paths=(), error=None):
        self.running = False
        self.finished.emit(paths, error)


@pytest.fixture
def preview(qapp, monkeypatch):
    import local_pdf_toolkit.ui.document_preview as embedded

    monkeypatch.setattr(embedded, "JobController", FakeJobs)
    widget = DocumentPreview()
    widget.resize(650, 650)
    widget.show()
    qapp.processEvents()
    yield widget
    if widget.jobs.running:
        widget.shutdown()
        widget.jobs.complete(error=("cancelled", "Cancelled"))
    widget.shutdown()
    widget.close()


def finish_page(widget, color="white", size=(400, 500), **extra):
    assert widget.jobs.running, "A preview worker must start before completing it."
    folder = Path(widget._temp.name)
    image = folder / "page.png"
    info = folder / "page.json"
    Image.new("RGBA", size, color).save(image)
    data = {
        "pages": 3,
        "page": widget.page.value(),
        "native_width": size[0],
        "native_height": size[1],
        "native_unit": "px",
        "source_bytes": 1234,
        "source_sha256": "a" * 64,
        "office_approximation": False,
    }
    data.update(extra)
    info.write_text(json.dumps(data))
    widget.jobs.complete((image, info))
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()


def wait_for_render(widget, count):
    deadline = time.monotonic() + 3
    while len(widget.jobs.started) < count and time.monotonic() < deadline:
        QTest.qWait(10)
    assert len(widget.jobs.started) == count and widget.jobs.running


def test_preview_is_lazy_debounced_and_rejects_old_selection(preview, tmp_path):
    one, two = tmp_path / "one.pdf", tmp_path / "two.pdf"
    preview.set_document(one)
    assert not preview.jobs.started
    preview.set_document(two)
    wait_for_render(preview, 1)
    assert len(preview.jobs.started) == 1
    assert preview.jobs.started[0][0] == two
    preview.set_document(one)
    assert preview.jobs.cancelled
    finish_page(preview, color="red")
    assert preview.canvas._image_rect.isEmpty()
    wait_for_render(preview, 2)
    assert preview.jobs.started[-1][0] == one
    finish_page(preview)
    assert not preview.canvas._image_rect.isEmpty()
    assert len(preview._cache) == 1


def test_original_result_stale_compare_and_matching_geometry_preserves_view(preview, tmp_path):
    source, result = tmp_path / "source.png", tmp_path / "result.png"
    preview.set_document(source, (result,), stale=True)
    assert preview.tabs.currentIndex() == 1
    preview.tabs.setCurrentIndex(0)
    assert not preview.stale_label.isHidden()
    assert preview.stale_label.text() == "Previous run — settings changed"
    compared = []
    preview.compare_requested.connect(lambda: compared.append(True))
    preview.compare_button.click()
    assert compared == [True]
    wait_for_render(preview, 1)
    finish_page(preview)
    preview.canvas.set_zoom(2)
    QTest.qWait(10)  # Let Qt lay out the scrollbars before the next user action.
    preview.canvas.centerOn(260, 330)
    old = preview.canvas.view_state()
    preview.tabs.setCurrentIndex(1)
    wait_for_render(preview, 2)
    assert preview.jobs.started[-1][0] == result
    finish_page(preview, color="blue")
    current = preview.canvas.view_state()
    assert current[0] == pytest.approx(old[0], rel=0.02)
    assert current[1:3] == pytest.approx(old[1:3], abs=0.02)
    assert not preview.canvas.fit_page
    preview.set_stale(False)
    assert preview.stale_label.isHidden()


def test_shutdown_waits_for_worker_before_removing_temp(preview, tmp_path):
    preview.set_document(tmp_path / "source.pdf")
    wait_for_render(preview, 1)
    folder = Path(preview._temp.name)
    marker = folder / "worker-owned"
    marker.write_text("still in use")
    idle = []
    preview.idle.connect(lambda: idle.append(True))
    assert not preview.shutdown()
    assert marker.exists() and preview.jobs.cancelled
    preview.jobs.complete(error=("cancelled", "Cancelled"))
    assert not folder.exists() and idle
    assert preview.shutdown()


def test_clear_during_worker_preserves_temporary_files_until_exit(preview, tmp_path):
    preview.set_document(tmp_path / "source.pdf")
    wait_for_render(preview, 1)
    marker = Path(preview._temp.name) / "worker-owned"
    marker.write_text("in use")
    preview.clear()
    assert marker.exists()
    preview.jobs.complete(error=("cancelled", "Cancelled"))
    assert not marker.exists()
    assert preview.canvas._image_rect.isEmpty()
    assert preview.feedback.text() == "Select a file to preview."


def test_busy_defers_debounce_and_resumes_only_latest_selection(preview, tmp_path):
    preview.set_document(tmp_path / "first.pdf")
    assert preview.set_busy(True)
    preview.set_document(tmp_path / "second.pdf")
    preview.set_document(tmp_path / "latest.pdf")
    QTest.qWait(180)
    assert not preview.jobs.started
    assert preview.set_busy(False)
    wait_for_render(preview, 1)
    assert len(preview.jobs.started) == 1
    assert preview.jobs.started[0][0] == tmp_path / "latest.pdf"
    finish_page(preview)
    assert preview.set_busy(True)
    assert preview.set_busy(False)
    QTest.qWait(180)
    assert len(preview.jobs.started) == 1  # Existing pixels need no new render.


def test_busy_cancels_active_render_and_preserves_pixels_and_cache(preview, tmp_path):
    preview.set_document(tmp_path / "source.pdf")
    wait_for_render(preview, 1)
    finish_page(preview, color="red")
    shown = preview.canvas.scene().items()[0].pixmap().cacheKey()
    preview.page.setValue(2)
    wait_for_render(preview, 2)
    assert preview.canvas.scene().items()[0].pixmap().cacheKey() == shown
    marker = Path(preview._temp.name) / "worker-owned"
    marker.write_text("in use")
    assert not preview.set_busy(True)
    assert preview.jobs.cancelled and marker.exists()
    # Even a successful result arriving after cancellation must stay off the UI.
    finish_page(preview, color="blue")
    assert preview.canvas.scene().items()[0].pixmap().cacheKey() == shown
    assert len(preview._cache) == 1 and marker.exists()
    preview.page.setValue(3)
    QTest.qWait(180)
    assert len(preview.jobs.started) == 2
    assert preview.set_busy(False)
    wait_for_render(preview, 3)
    assert len(preview.jobs.started) == 3
    assert preview.jobs.started[-1][2] == {"page": 3}
    finish_page(preview, color="green")
    assert len(preview._cache) == 2


def test_busy_resume_waits_for_cancelled_worker_exit(preview, tmp_path):
    preview.set_document(tmp_path / "first.pdf")
    wait_for_render(preview, 1)
    assert not preview.set_busy(True)
    preview.set_document(tmp_path / "latest.pdf")
    assert not preview.set_busy(False)
    QTest.qWait(180)
    assert len(preview.jobs.started) == 1
    preview.jobs.complete(error=("cancelled", "Cancelled"))
    wait_for_render(preview, 2)
    assert len(preview.jobs.started) == 2
    assert preview.jobs.started[-1][0] == tmp_path / "latest.pdf"
    assert not preview.shutdown()
    folder = Path(preview._temp.name)
    preview.jobs.complete(error=("cancelled", "Cancelled"))
    assert not folder.exists()


def test_media_has_clear_preview_explanation(preview, tmp_path):
    preview.set_document(tmp_path / "audio.mp3")
    QTest.qWait(180)
    assert not preview.jobs.started
    assert "Audio and video previews are unavailable" in preview.feedback.text()


def test_embedded_preview_real_worker(qapp, fixture_dir):
    from PySide6.QtCore import QEventLoop

    widget = DocumentPreview()
    widget.set_document(fixture_dir / "one_page.pdf")
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(15000)
    widget.jobs.finished.connect(loop.quit)
    loop.exec()
    timeout.stop()
    assert not widget.jobs.running
    assert not widget.canvas._image_rect.isEmpty()
    assert widget.page.maximum() == 1
    folder = Path(widget._temp.name)
    assert widget.shutdown()
    widget.close()
    assert not folder.exists()
