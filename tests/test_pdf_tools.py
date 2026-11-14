import hashlib
from pathlib import Path

import pymupdf
import pytest

from local_pdf_toolkit.converters.pdf_tools import (
    PdfToolConverter,
    ordered_pages,
    pdf_tool_converters,
)
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        for text in ("First", "Second", "Third"):
            document.new_page(width=240, height=300).insert_text((20, 40), text)
        document.set_metadata({"title": "Private title", "author": "Private author"})
        document.set_xml_metadata("<metadata>private</metadata>")
        document.save(path)
    return path


def convert(operation, source, output, options=None, progress=None, token=None):
    return PdfToolConverter(operation).convert(
        source, output, options or {}, progress or (lambda _: None), token or CancellationToken()
    )


def texts(path):
    with pymupdf.open(path) as document:
        return [page.get_text().strip() for page in document]


def test_factory():
    converters = pdf_tool_converters()
    assert len(converters) == 15
    assert len({converter.spec.operation_id for converter in converters}) == 15
    assert PdfToolConverter("merge").spec.input_mode == "multiple"
    assert PdfToolConverter("to_text").spec.output_formats == (FileFormat.TXT,)


def test_merge_order_and_preserves_originals(pdf, tmp_path):
    other = tmp_path / "other.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((30, 40), "Other")
        document.save(other)
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in (pdf, other)}
    updates = []
    (result,) = convert("merge", (other, pdf), tmp_path, progress=updates.append)
    assert texts(result) == ["Other", "First", "Second", "Third"]
    assert updates[-1].completed == updates[-1].total == 2
    assert all(
        hashlib.sha256(path.read_bytes()).digest() == digest for path, digest in before.items()
    )


@pytest.mark.parametrize(
    "operation, options, expected",
    [
        ("extract", {"pages": "3,1"}, ["First", "Third"]),
        ("reorder", {"order": "3,1-2"}, ["Third", "First", "Second"]),
        ("delete", {"pages": "2"}, ["First", "Third"]),
    ],
)
def test_page_selection_operations(pdf, tmp_path, operation, options, expected):
    (result,) = convert(operation, pdf, tmp_path, options)
    assert texts(result) == expected
    assert texts(pdf) == ["First", "Second", "Third"]


def test_split_selected_pages(pdf, tmp_path):
    results = convert("split", pdf, tmp_path, {"pages": "3,1"})
    assert [path.name for path in results] == ["source_page-0001.pdf", "source_page-0003.pdf"]
    assert [texts(path) for path in results] == [["First"], ["Third"]]


def test_rotate_adds_to_existing_rotation(pdf, tmp_path):
    rotated = tmp_path / "rotated.pdf"
    with pymupdf.open(pdf) as document:
        document[1].set_rotation(90)
        document.save(rotated)
    (result,) = convert("rotate", rotated, tmp_path, {"pages": "2", "angle": 270})
    with pymupdf.open(result) as document:
        assert [page.rotation for page in document] == [0, 0, 0]
    with pymupdf.open(rotated) as document:
        assert document[1].rotation == 90


def test_crop_selected_pages(pdf, tmp_path):
    (result,) = convert(
        "crop",
        pdf,
        tmp_path,
        {
            "pages": "2",
            "left": 10,
            "top": 15,
            "right": 20,
            "bottom": 25,
        },
    )
    with pymupdf.open(result) as document:
        assert document[0].cropbox == pymupdf.Rect(0, 0, 240, 300)
        assert document[1].cropbox == pymupdf.Rect(10, 15, 220, 275)


def test_number_and_watermark_selected_pages(pdf, tmp_path):
    (numbered,) = convert("number", pdf, tmp_path, {"pages": "2-3", "start": 7})
    assert texts(numbered) == ["First", "Second\n7", "Third\n8"]
    (marked,) = convert("watermark", pdf, tmp_path, {"pages": "1", "text": "COPY"})
    assert texts(marked) == ["First\nCOPY", "Second", "Third"]


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_numbers_are_at_displayed_bottom_on_rotated_pages(pdf, tmp_path, angle):
    rotated = tmp_path / "rotated.pdf"
    with pymupdf.open(pdf) as document:
        document[0].set_rotation(angle)
        document.save(rotated)
    (result,) = convert("number", rotated, tmp_path, {"pages": "1"})
    with pymupdf.open(result) as document:
        page = document[0]
        spans = [
            span
            for block in page.get_text("dict")["blocks"]
            for line in block["lines"]
            for span in line["spans"]
        ]
        number = next(span for span in spans if span["text"] == "1")
        origin = pymupdf.Point(number["origin"]) * page.rotation_matrix
        expected_x = (page.rect.width - pymupdf.get_text_length("1", fontsize=12)) / 2
        assert origin.x == pytest.approx(expected_x, abs=0.01)
        assert origin.y == pytest.approx(page.rect.height - 12)


def test_remove_metadata(pdf, tmp_path):
    (result,) = convert("remove_metadata", pdf, tmp_path)
    with pymupdf.open(result) as document:
        assert not document.metadata["title"]
        assert not document.metadata["author"]
        assert not document.get_xml_metadata()
    with pymupdf.open(pdf) as document:
        assert document.metadata["title"] == "Private title"


def test_flatten_forms_and_annotations(pdf, tmp_path):
    annotated = tmp_path / "annotated.pdf"
    with pymupdf.open(pdf) as document:
        page = document[0]
        page.add_rect_annot(pymupdf.Rect(15, 20, 80, 50))
        widget = pymupdf.Widget()
        widget.field_name = "name"
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.field_value = "Visible field"
        widget.rect = pymupdf.Rect(20, 100, 200, 130)
        page.add_widget(widget)
        document.save(annotated)
    (result,) = convert("flatten", annotated, tmp_path)
    with pymupdf.open(result) as document:
        assert list(document[0].annots()) == []
        assert list(document[0].widgets()) == []
        assert "Visible field" in document[0].get_text()
    with pymupdf.open(annotated) as document:
        assert len(list(document[0].annots())) == 1
        assert len(list(document[0].widgets())) == 1


def test_protect_and_unlock_with_authentication(pdf, tmp_path):
    (locked,) = convert("protect", pdf, tmp_path, {"password": "correct horse"})
    with pymupdf.open(locked) as document:
        assert document.needs_pass
        assert document.authenticate("correct horse")
        assert "256-bit AES" in document.metadata["encryption"]
    assert PdfToolConverter("unlock").validate_input(locked) == FileFormat.PDF
    with pytest.raises(ConversionError) as error:
        convert("unlock", locked, tmp_path, {"password": "wrong"})
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED
    assert not (tmp_path / "source_protect_unlock.pdf").exists()
    (result,) = convert("unlock", locked, tmp_path, {"password": "correct horse"})
    assert texts(result) == texts(pdf)
    with pymupdf.open(result) as document:
        assert not document.needs_pass
        assert not document.metadata["encryption"]


def test_unlock_requires_password_for_owner_only_encryption(pdf, tmp_path):
    locked = tmp_path / "owner.pdf"
    with pymupdf.open(pdf) as document:
        document.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner")
    with pytest.raises(ConversionError) as error:
        convert("unlock", locked, tmp_path, {"password": "wrong"})
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED
    (result,) = convert("unlock", locked, tmp_path, {"password": "owner"})
    assert texts(result) == texts(pdf)


def test_text_and_markdown_exports(pdf, tmp_path):
    (plain,) = convert("to_text", pdf, tmp_path, {"pages": "2"})
    assert "Second" in plain.read_text(encoding="utf-8")
    assert "First" not in plain.read_text(encoding="utf-8")
    (markdown,) = convert("to_markdown", pdf, tmp_path, {"pages": "3"})
    assert markdown.read_text(encoding="utf-8") == "## Page 3\n\nThird\n\n"


def test_reserved_windows_output_name_is_safe(pdf, tmp_path):
    renamed = tmp_path / "CON.extra.pdf"
    pdf.rename(renamed)
    (result,) = convert("to_text", renamed, tmp_path)
    assert result.name == "_CON.extra.txt"


@pytest.mark.parametrize(
    "operation, options",
    [
        ("delete", {}),
        ("rotate", {"angle": True}),
        ("rotate", {"angle": 45}),
        ("crop", {"left": -1}),
        ("crop", {"left": 240}),
        ("watermark", {"text": "😀"}),
        ("watermark", {"text": "x" * 200}),
        ("protect", {"password": ""}),
        ("protect", {"password": "é" * 64}),
        ("extract", {"pages": "4"}),
        ("reorder", {"order": "3,1"}),
        ("reorder", {"order": "1,1,3"}),
        ("extract", {"bogus": True}),
    ],
)
def test_invalid_options_publish_nothing(pdf, tmp_path, operation, options):
    before = pdf.read_bytes()
    with pytest.raises(ConversionError) as error:
        convert(operation, pdf, tmp_path, options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS
    assert list(tmp_path.iterdir()) == [pdf]
    assert pdf.read_bytes() == before


@pytest.mark.parametrize("source", [(Path("missing"),), "missing", (Path("missing"), 5)])
def test_invalid_merge_inputs(source, tmp_path):
    with pytest.raises(ConversionError) as error:
        convert("merge", source, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT


def test_bad_pdf_and_encrypted_input_rejected(pdf, tmp_path):
    corrupt = tmp_path / "broken.pdf"
    corrupt.write_bytes(b"%PDF-1.7\nbroken")
    with pytest.raises(ConversionError) as error:
        convert("extract", corrupt, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT
    (locked,) = convert("protect", pdf, tmp_path, {"password": "secret"})
    with pytest.raises(ConversionError) as error:
        convert("rotate", locked, tmp_path)
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED


def test_no_overwrite_and_cancellation_cleanup(pdf, tmp_path):
    existing = tmp_path / "source_page-0002.pdf"
    existing.write_bytes(b"existing")
    with pytest.raises(ConversionError) as error:
        convert("split", pdf, tmp_path)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert not (tmp_path / "source_page-0001.pdf").exists()
    assert existing.read_bytes() == b"existing"
    existing.unlink()
    token = CancellationToken()

    def cancel(progress):
        if progress.completed == 1:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        convert("split", pdf, tmp_path, progress=cancel, token=token)
    assert list(tmp_path.iterdir()) == [pdf]


def test_order_parser_keeps_explicit_sequence():
    assert ordered_pages("3-4,1-2", 4) == (2, 3, 0, 1)
