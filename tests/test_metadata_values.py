import pymupdf
from PIL import Image

from local_pdf_toolkit.ui.metadata_values import metadata_values


def test_local_values_include_pdf_author(tmp_path):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.set_metadata({"author": "Private Author"})
        doc.save(source)
    assert ("PDF author", "Private Author") in metadata_values(source)


def test_dialog_displays_values_from_background_reader(qapp, tmp_path):
    from PySide6.QtCore import QEventLoop, QTimer

    from local_pdf_toolkit.ui.metadata_values import MetadataValuesDialog

    source = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.set_metadata({"author": "Private Author"})
        doc.save(source)
    dialog = MetadataValuesDialog([source])
    dialog.show()
    loop = QEventLoop()
    dialog.text.textChanged.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    if dialog.text.toPlainText() == "Reading metadata…":
        loop.exec()
    assert "PDF author: Private Author" in dialog.text.toPlainText()
    dialog.close()


def test_local_values_include_image_author_and_gps(tmp_path):
    source = tmp_path / "source.jpg"
    exif = Image.Exif()
    exif[315] = "Private Photographer"
    exif[34853] = {1: "N", 2: (40.0, 30.0, 0.0), 3: "W", 4: (73.0, 0.0, 0.0)}
    Image.new("RGB", (10, 10)).save(source, exif=exif)
    values = dict(metadata_values(source))
    assert values["EXIF Artist"] == "Private Photographer"
    assert values["GPS GPSLatitudeRef"] == "N"
    assert "40" in values["GPS GPSLatitude"]


def test_local_values_include_office_author(tmp_path):
    from docx import Document

    source = tmp_path / "source.docx"
    doc = Document()
    doc.core_properties.author = "Private Author"
    doc.save(source)
    assert ("Document creator", "Private Author") in metadata_values(source)


def test_metadata_action_opens_the_inspected_pair(qapp, tmp_path, monkeypatch):
    from local_pdf_toolkit.app import build_registry
    from local_pdf_toolkit.ui import metadata_values as viewer
    from local_pdf_toolkit.ui.main_window import MainWindow

    opened = []

    class FakeDialog:
        def __init__(self, paths, parent):
            opened.append(tuple(paths))

        def exec(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(viewer, "MetadataValuesDialog", FakeDialog)
    window = MainWindow(build_registry())
    window.show()
    try:
        window._select_tool(
            next(
                i
                for i, spec in enumerate(window._operations)
                if spec.operation_id == "metadata.inspect"
            )
        )
        paths = [tmp_path / "before.pdf", tmp_path / "after.pdf", tmp_path / "other.pdf"]
        window._paths = paths
        window.files.addItems([path.name for path in paths])
        window.files.setCurrentRow(0)
        report = (tmp_path / "report.json",)
        window._results = {0: report, 1: report}
        window._sync_comparison()
        assert window.result_metadata.isVisible()
        assert window.result_open.text() == "View report"
        assert not window.document_preview.tabs.isTabVisible(1)
        window.result_metadata.click()
        assert opened == [tuple(paths[:2])]
    finally:
        window.close()


def test_pdf_xmp_values_are_read(tmp_path):
    source = tmp_path / "source.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.set_xml_metadata("""<x:xmpmeta xmlns:x="adobe:ns:meta/"
            xmlns:dc="http://purl.org/dc/elements/1.1/">
            <dc:creator>Private XMP creator</dc:creator></x:xmpmeta>""")
        doc.save(source)
    assert ("XMP creator", "Private XMP creator") in metadata_values(source)


def test_office_custom_properties_and_duplicate_rejection(tmp_path):
    from zipfile import ZipFile

    import pytest

    source = tmp_path / "source.docx"
    custom = b"""<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"
      xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
      <property name="Client"><vt:lpwstr>Private Client</vt:lpwstr></property></Properties>"""
    with ZipFile(source, "w") as archive:
        archive.writestr("docProps/custom.xml", custom)
    assert ("Custom Client", "Private Client") in metadata_values(source)
    with ZipFile(source, "a") as archive:
        with pytest.warns(UserWarning):
            archive.writestr("docProps/custom.xml", custom)
    with pytest.raises(ValueError, match="Duplicate"):
        metadata_values(source)


def test_dialog_search_filters_displayed_values(qapp):
    from local_pdf_toolkit.ui.metadata_values import MetadataValuesDialog

    dialog = MetadataValuesDialog([])
    dialog._set_contents(
        "FILE 1: example.pdf\n[Author and ownership]\nPDF author: Alice\n"
        "[Location]\nGPS city: Paris"
    )
    dialog.search.setText("paris")
    assert "GPS city: Paris" in dialog.text.toPlainText()
    assert "Alice" not in dialog.text.toPlainText()
    dialog.search.clear()
    assert "Alice" in dialog.text.toPlainText()
    dialog.close()


def test_media_values_and_masked_inspection(tmp_path):
    import json
    import shutil
    import subprocess

    import pytest

    from local_pdf_toolkit.converters.inspector import MetadataInspector
    from local_pdf_toolkit.core.contracts import CancellationToken

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe are not installed")
    audio, video = tmp_path / "audio.flac", tmp_path / "video.mp4"
    for source, output, codec in (
        ("sine=frequency=440:duration=1", audio, "flac"),
        ("color=black:size=16x16:duration=1", video, "mpeg4"),
    ):
        subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                source,
                "-metadata",
                "artist=Private Media Artist",
                "-c:a" if output == audio else "-c:v",
                codec,
                "-y",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        assert ("Media artist", "Private Media Artist") in metadata_values(output)
    (report,) = MetadataInspector().convert(
        (audio, video), tmp_path, {}, lambda _: None, CancellationToken()
    )
    text = report.read_text(encoding="utf-8")
    assert "Private Media Artist" not in text
    inspection = json.loads(text)["inspection"]
    assert all(item["counts"]["metadata_tags"] > 0 for item in inspection)


def test_media_values_explain_missing_probe(tmp_path, monkeypatch):
    import pytest

    from local_pdf_toolkit.converters import media_metadata
    from local_pdf_toolkit.ui import metadata_values as viewer

    source = tmp_path / "audio.mp3"
    source.write_bytes(b"not media")
    monkeypatch.setattr(media_metadata, "find_ffmpeg", lambda: None)
    monkeypatch.setattr(viewer.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="ffprobe"):
        viewer.metadata_values(source)
