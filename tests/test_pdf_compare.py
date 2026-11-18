import hashlib

import pymupdf
import pytest
from PIL import Image

from local_pdf_toolkit.converters import pdf_compare
from local_pdf_toolkit.converters.pdf_compare import PdfComparisonConverter, difference_mask
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode


def pdf(path, pages):
    with pymupdf.open() as document:
        for width, height, text in pages:
            page = document.new_page(width=width, height=height)
            if text:
                page.insert_text((15, 30), text)
        document.save(path)
    return path


def compare(first, second, output, options=None, progress=lambda _: None, token=None):
    return PdfComparisonConverter().convert(
        (first, second), output, options or {}, progress, token or CancellationToken()
    )


def test_identical_comparison_reports_no_detected_differences_and_preserves_sources(tmp_path):
    first = pdf(tmp_path / "first.pdf", [(150, 100, "Same")])
    second = pdf(tmp_path / "second.pdf", [(150, 100, "Same")])
    originals = {path: hashlib.sha256(path.read_bytes()).digest() for path in (first, second)}
    report, text = compare(first, second, tmp_path)
    assert "Page 1: no differences detected; 0 differing pixels" in text.read_text()
    with pymupdf.open(report) as document:
        assert len(document) == 1
        assert "corresponding page numbers" in document[0].get_text()
    assert originals == {path: hashlib.sha256(path.read_bytes()).digest() for path in originals}
    prior = report.read_bytes(), text.read_bytes()
    with pytest.raises(ConversionError) as error:
        compare(first, second, tmp_path)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert (report.read_bytes(), text.read_bytes()) == prior


def test_changed_pages_have_text_diff_and_highlighted_visual_review(tmp_path):
    first = pdf(tmp_path / "first.pdf", [(150, 100, "Old text")])
    second = pdf(tmp_path / "second.pdf", [(150, 100, "New text")])
    report, text = compare(first, second, tmp_path)
    content = text.read_text()
    assert "Page 1: changed" in content
    assert "-Old text" in content and "+New text" in content
    with pymupdf.open(report) as document:
        assert len(document) == 2
        assert "First PDF" in document[1].get_text()
        pixmap = document[1].get_pixmap()
        with Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples) as image:
            assert any(
                red > 240 and green < 20 and blue > 140
                for red, green, blue in image.get_flattened_data()
            )


def test_missing_and_resized_blank_pages_are_changes_even_without_pixel_delta(tmp_path):
    first = pdf(tmp_path / "first.pdf", [(100, 100, ""), (100, 100, "")])
    second = pdf(tmp_path / "second.pdf", [(120, 100, "")])
    report, text = compare(first, second, tmp_path)
    content = text.read_text()
    assert "page size changed" in content
    assert "Page 2: missing from second; 0 differing pixels" in content
    with pymupdf.open(report) as document:
        assert len(document) == 3
        assert "MISSING PAGE" in document[2].get_text()


def test_pixel_tolerance_uses_strongest_channel_and_strict_threshold():
    with Image.new("RGB", (2, 1), (250, 250, 250)) as first:
        with Image.new("RGB", (2, 1), (234, 250, 250)) as second:
            second.putpixel((1, 0), (250, 233, 250))
            with difference_mask(first, second, 16) as mask:
                assert list(mask.get_flattened_data()) == [0, 255]


def test_text_limit_never_claims_complete_text_equality(tmp_path, monkeypatch):
    first = pdf(tmp_path / "first.pdf", [(150, 100, "Prefix OLD")])
    second = pdf(tmp_path / "second.pdf", [(150, 100, "Prefix NEW")])
    monkeypatch.setattr(pdf_compare, "MAX_TEXT_CHARS", 6)
    _, text = compare(first, second, tmp_path)
    assert "text comparison incomplete" in text.read_text()
    assert "unreported text may differ" in text.read_text()


def test_limits_cancellation_and_invalid_pairs_publish_nothing(tmp_path, monkeypatch):
    first = pdf(tmp_path / "first.pdf", [(100, 100, "A"), (100, 100, "B")])
    second = pdf(tmp_path / "second.pdf", [(100, 100, "A")])
    output = tmp_path / "output"
    output.mkdir()
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        compare(
            first,
            second,
            output,
            progress=lambda progress: token.cancel() if progress.completed == 1 else None,
            token=token,
        )
    assert not list(output.iterdir())
    monkeypatch.setattr(pdf_compare, "MAX_TOTAL_PIXELS", 1)
    with pytest.raises(ConversionError, match="rendered pixels"):
        compare(first, second, output)
    monkeypatch.setattr(pdf_compare, "MAX_COMPARE_PAGES", 1)
    with pytest.raises(ConversionError, match="at most"):
        compare(first, second, output)
    for invalid in (first, (first,), (first, second, first), (first, 10)):
        with pytest.raises(ConversionError, match="exactly two"):
            PdfComparisonConverter().validate_input(invalid)
    for options in ({"threshold": True}, {"threshold": 256}, {"dpi": 35}, {"unknown": 0}):
        with pytest.raises(ConversionError):
            PdfComparisonConverter().validate_options(options)
    assert not list(output.iterdir())


def test_corrupt_and_encrypted_pdf_rejected(tmp_path):
    first = pdf(tmp_path / "first.pdf", [(100, 100, "A")])
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not pdf")
    with pytest.raises(ConversionError):
        PdfComparisonConverter().validate_input((first, corrupt))
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open(first) as document:
        document.save(
            encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
    with pytest.raises(ConversionError) as error:
        PdfComparisonConverter().validate_input((first, encrypted))
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED
