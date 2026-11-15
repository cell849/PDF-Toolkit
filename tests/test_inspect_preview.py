import json
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, PngImagePlugin
from PySide6.QtCore import QEventLoop, QTimer

from local_pdf_toolkit.converters.image_metadata import ImageMetadataConverter
from local_pdf_toolkit.converters.inspector import MetadataInspector
from local_pdf_toolkit.converters.preview import PreviewConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionError
from local_pdf_toolkit.ui.preview import PreviewDialog


def run(converter, paths, folder, options=None):
    return converter.convert(paths, folder, options or {}, lambda _: None, CancellationToken())


def test_masked_image_comparison_uses_actual_fields(tmp_path):
    source = tmp_path / "PrivateOwner.png"
    tags = PngImagePlugin.PngInfo()
    tags.add_text("Private field name", "Private value")
    exif = Image.Exif()
    exif[315] = "Private author"
    Image.new("RGB", (20, 30), "red").save(source, pnginfo=tags, exif=exif)
    cleaned, _ = run(ImageMetadataConverter(), source, tmp_path)
    (report,) = run(MetadataInspector(), (source, cleaned), tmp_path)
    text = report.read_text()
    data = json.loads(text)
    assert "Private" not in text
    assert data["inspection"][0]["fields_detected"] > 0
    assert data["inspection"][1]["fields_detected"] == 0
    assert any(row["before"] > row["after"] for row in data["comparison"])


def test_office_inspection_counts_without_values(tmp_path):
    from docx import Document

    source = tmp_path / "Private.docx"
    doc = Document()
    doc.core_properties.author = "PrivateOwner"
    doc.add_paragraph("Private visible text")
    doc.save(source)
    (report,) = run(MetadataInspector(), source, tmp_path)
    assert "Private" not in report.read_text()
    assert json.loads(report.read_text())["inspection"][0]["fields_detected"] > 0


def test_pdf_previews_are_paged_bounded_and_preserve_source(tmp_path):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=72, height=144).insert_text((10, 30), "First")
        doc.new_page(width=144, height=72).insert_text((10, 30), "Second")
        doc.save(source)
    before = source.read_bytes()
    image, info = run(PreviewConverter(), source, tmp_path, {"page": 2})
    data = json.loads(info.read_text())
    assert data["pages"] == 2 and data["width"] > data["height"]
    with Image.open(image) as picture:
        assert max(picture.size) <= 1400
    assert source.read_bytes() == before
    with pytest.raises(ConversionError):
        run(PreviewConverter(), source, tmp_path, {"page": 3})


def test_preview_image_exif_and_alpha(tmp_path):
    source = tmp_path / "source.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (20, 40), "red").save(source, exif=exif)
    image, _ = run(PreviewConverter(), source, tmp_path)
    with Image.open(image) as result:
        assert result.size == (40, 20)
        assert not result.getexif()


def test_preview_dialog_worker_and_temp_cleanup(qapp, fixture_dir):
    dialog = PreviewDialog(fixture_dir / "one_page.pdf")
    folder = Path(dialog._temp.name)
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(15000)
    dialog.jobs.finished.connect(loop.quit)
    loop.exec()
    timeout.stop()
    assert not dialog.jobs.running
    assert not dialog.canvas._image_rect.isEmpty()
    dialog.close()
    qapp.processEvents()
    assert not folder.exists()


def test_marking_uses_normalized_display_coordinates(qapp, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from local_pdf_toolkit.ui.preview import PageCanvas

    path = tmp_path / "page.png"
    Image.new("RGB", (400, 200), "white").save(path)
    canvas = PageCanvas()
    canvas.resize(800, 600)
    canvas._marking = True
    canvas.show()
    canvas.load(path)
    qapp.processEvents()
    start = canvas.mapFromScene(100, 50)
    end = canvas.mapFromScene(300, 150)
    QTest.mousePress(canvas.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(canvas.viewport(), end)
    QTest.mouseRelease(canvas.viewport(), Qt.LeftButton, pos=end)
    assert len(canvas.regions) == 1
    assert canvas.regions[0] == pytest.approx((0.25, 0.25, 0.75, 0.75), abs=0.01)
    canvas.resize(500, 400)
    qapp.processEvents()
    assert canvas.regions[0] == pytest.approx((0.25, 0.25, 0.75, 0.75), abs=0.01)
    canvas.close()


def test_redaction_marks_are_bound_to_unchanged_source(qapp, tmp_path):
    from local_pdf_toolkit.app import build_registry
    from local_pdf_toolkit.ui.main_window import MainWindow
    from local_pdf_toolkit.ui.redaction import RedactionControl, signature

    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    window = MainWindow(build_registry())
    window.add_paths([source])
    control = RedactionControl(window)
    control.bound_source = signature(window._paths)
    control.marked = {1: [(0.1, 0.2, 0.3, 0.4)]}
    assert json.loads(control.value())[0]["x0"] == 0.1
    source.write_bytes(b"changed source")
    assert control.value() == "[]"
    window.add_paths([tmp_path / "another.pdf"])
    assert control.value() == "[]"
    window.close()


def test_marking_rejects_previous_marks_for_replaced_content(qapp, fixture_dir):
    dialog = PreviewDialog(
        fixture_dir / "one_page.pdf",
        marking=True,
        regions={1: [(0.1, 0.1, 0.3, 0.3)]},
        source_digest="0" * 64,
    )
    loop = QEventLoop()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(15000)
    dialog.jobs.finished.connect(loop.quit)
    loop.exec()
    timer.stop()
    assert not dialog.jobs.running
    assert not dialog.done_button.isEnabled()
    assert "source changed" in dialog.feedback.text()
    assert dialog.canvas._image_rect.isEmpty()
    dialog.close()
