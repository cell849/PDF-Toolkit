import json
from types import SimpleNamespace

import pymupdf
import pytest
from PIL import Image

import local_pdf_toolkit.converters.document_details as module
from local_pdf_toolkit.converters.document_details import DocumentDetailsConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


def run(source, folder, token=None):
    (report,) = DocumentDetailsConverter().convert(
        source, folder, {}, lambda _: None, token or CancellationToken()
    )
    return json.loads(report.read_text()), report


def test_pdf_fonts_page_geometry_and_attachment_names_without_extraction(tmp_path):
    source = tmp_path / "private.pdf"
    with pymupdf.open() as document:
        document.new_page(width=200, height=300).insert_text((20, 50), "Private visible text")
        document.new_page(width=300, height=200).insert_text((20, 50), "Second")
        document.embfile_add("private.txt", b"DO NOT EXTRACT THIS", filename="private.txt")
        document.save(source)
    before = source.read_bytes()
    report, path = run(source, tmp_path)
    details = report["document_details"]
    assert details["format"] == "pdf" and details["page_count"] == 2
    assert details["pages"][0] == {
        "page": 1,
        "width_pt": 200,
        "height_pt": 300,
        "rotation_degrees": 0,
    }
    assert details["pages"][1]["width_pt"] == 300
    assert details["fonts"] == [{"name": "Helvetica", "type": "Type1", "embedded": False}]
    assert details["attachments"] == [{"name": "private.txt", "bytes": 19}]
    assert details["attachment_count"] == 1 and not details["encrypted"]
    assert "DO NOT EXTRACT THIS" not in path.read_text()
    assert str(tmp_path) not in path.read_text()
    assert source.read_bytes() == before
    assert {item.name for item in tmp_path.iterdir()} == {source.name, path.name}


def test_locked_pdf_reports_encryption_without_attempting_content_access(tmp_path):
    source = tmp_path / "locked.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((20, 50), "Hidden")
        document.save(
            source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
    report, _ = run(source, tmp_path)
    details = report["document_details"]
    assert details["encrypted"] and details["password_required"]
    assert details["page_count"] == 1
    assert not {"fonts", "pages", "attachments"} & details.keys()
    assert "locked" in " ".join(report["limits"]).lower()
    assert DocumentDetailsConverter().validate_input(source) == FileFormat.PDF


def test_lists_are_bounded_and_omissions_explicit(tmp_path, monkeypatch):
    source = tmp_path / "many.pdf"
    with pymupdf.open() as document:
        for _ in range(3):
            document.new_page().insert_text((20, 50), "One font")
        for index in range(3):
            document.embfile_add(f"attachment-{index}", b"payload")
        document.save(source)
    monkeypatch.setattr(module, "MAX_PAGE_DETAILS", 1)
    monkeypatch.setattr(module, "MAX_ATTACHMENTS", 1)
    report, _ = run(source, tmp_path)
    details = report["document_details"]
    assert details["page_count"] == 3 and len(details["pages"]) == 1
    assert details["attachment_count"] == 3 and len(details["attachments"]) == 1
    assert "first 1 pages" in " ".join(report["limits"])
    assert "first 1 attachment" in " ".join(report["limits"])


def test_image_dpi_and_mode_are_details_not_a_resize(tmp_path):
    source = tmp_path / "photo.png"
    Image.new("RGBA", (30, 20), "red").save(source, dpi=(276, 150))
    before = source.read_bytes()
    report, _ = run(source, tmp_path)
    details = report["document_details"]
    assert (details["width_px"], details["height_px"], details["mode"]) == (30, 20, "RGBA")
    assert details["dpi"] == pytest.approx((276, 150), abs=0.02)
    assert source.read_bytes() == before


def test_office_structural_counts_do_not_render_or_expose_text(tmp_path):
    from docx import Document

    source = tmp_path / "document.docx"
    document = Document()
    document.add_paragraph("Private text")
    document.add_paragraph("Another")
    document.save(source)
    report, path = run(source, tmp_path)
    details = report["document_details"]
    assert details["format"] == "docx" and details["paragraph_count"] == 2
    assert details["table_count"] == 0 and details["package_parts"] > 0
    assert details["uncompressed_bytes"] > details["source_bytes"]
    assert "Private" not in path.read_text()
    assert "Rendered page" in " ".join(report["limits"])


def test_corrupt_and_oversized_office_package_publish_nothing(tmp_path, monkeypatch):
    import zipfile

    source = tmp_path / "bad.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", b"<bad>")
    with pytest.raises(ConversionError):
        run(source, tmp_path)
    assert list(tmp_path.iterdir()) == [source]
    import local_pdf_toolkit.converters.office_pdf as office

    monkeypatch.setattr(office, "MAX_INPUT_BYTES", 1000)
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("word/document.xml", b"<document/>")
        package.writestr("large.xml", b"x" * 2000)
    assert source.stat().st_size < 1000
    with pytest.raises(ConversionError):
        run(source, tmp_path)
    assert list(tmp_path.iterdir()) == [source]
    source.write_bytes(b"%PDF-1.7\ncorrupt")
    with pytest.raises(ConversionError):
        run(source, tmp_path)
    assert list(tmp_path.iterdir()) == [source]


def test_report_collision_and_cancellation_preserve_existing_files(tmp_path, monkeypatch):
    source = tmp_path / "photo.png"
    Image.new("RGB", (3, 4)).save(source)
    monkeypatch.setattr(module, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    first, path = run(source, tmp_path)
    before = path.read_bytes()
    with pytest.raises(ConversionError) as error:
        run(source, tmp_path)
    assert error.value.code == ErrorCode.OUTPUT_ERROR and path.read_bytes() == before
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConversionError) as error:
        run(source, tmp_path, token)
    assert error.value.code == ErrorCode.CANCELLED
    assert {item.name for item in tmp_path.iterdir()} == {source.name, path.name}


def test_long_detail_lists_fit_the_report_reader_limit_and_disclose_omissions():
    details = {
        "format": "pdf",
        "fonts": [{"name": "\U0001f600" * 256} for _ in range(256)],
        "attachments": [{"name": "\U0001f600" * 256} for _ in range(100)],
    }
    text = module._report_text(details, [])
    report = json.loads(text)
    assert len(text.encode("utf-8")) <= 64 * 1024
    omitted = report["document_details"]["report_list_omissions"]["fonts"]
    assert omitted + len(details["fonts"]) == 256
    assert "shortened" in " ".join(report["limits"])
