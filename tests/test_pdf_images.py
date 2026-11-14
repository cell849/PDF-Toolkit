import hashlib
from pathlib import Path

import pymupdf
import pytest

from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter, page_selection
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "résumé.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=72, height=144).insert_text((10, 30), "Test")
        doc.new_page(width=144, height=72)
        doc.save(path)
    return path


@pytest.mark.parametrize("format", [FileFormat.JPEG, FileFormat.PNG])
@pytest.mark.parametrize("dpi", [72, 150, 300])
def test_render_pages_dimensions_and_original(pdf, tmp_path, format, dpi):
    before = hashlib.sha256(pdf.read_bytes()).digest()
    out = tmp_path / "out"
    out.mkdir()
    updates = []
    converter = PdfImagesConverter(format)
    paths = converter.convert(pdf, out, {"dpi": dpi}, updates.append, CancellationToken())
    assert len(paths) == 2
    assert paths[0].stem == "résumé_page-0001"
    first, second = map(pymupdf.Pixmap, map(str, paths))
    assert (first.width, first.height) == (dpi, dpi * 2)
    assert (second.width, second.height) == (dpi * 2, dpi)
    assert updates[-1].completed == updates[-1].total == 2
    assert hashlib.sha256(pdf.read_bytes()).digest() == before
    assert len(list(out.iterdir())) == 2


def test_png_alpha_and_page_selection(pdf, tmp_path):
    paths = PdfImagesConverter(FileFormat.PNG).convert(
        pdf, tmp_path, {"pages": "2,2", "alpha": True}, lambda _: None, CancellationToken()
    )
    assert len(paths) == 1
    image = pymupdf.Pixmap(str(paths[0]))
    assert image.alpha
    assert image.pixel(0, 0)[-1] == 0
    assert paths[0].name.endswith("0002.png")


@pytest.mark.parametrize("text", ["0", "3", "2-1", "1,", "-1", "1.5", "no"])
def test_bad_ranges(text):
    with pytest.raises(ConversionError, match="pages|Pages|Use"):
        page_selection(text, 2)


def test_ranges_are_unique_in_document_order():
    assert page_selection("3,1-2,2", 3) == (0, 1, 2)


@pytest.mark.parametrize(
    "options",
    [{"dpi": 1}, {"quality": 0}, {"quality": True}, {"pages": 1}, {"extra": 1}, {"quality": 101}],
)
def test_bad_options(options):
    with pytest.raises(ConversionError) as error:
        PdfImagesConverter(FileFormat.JPEG).validate_options(options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_existing_output_is_preserved(pdf, tmp_path):
    existing = tmp_path / "résumé_page-0002.jpg"
    existing.write_bytes(b"keep")
    with pytest.raises(ConversionError):
        PdfImagesConverter(FileFormat.JPEG).convert(
            pdf, tmp_path, {}, lambda _: None, CancellationToken()
        )
    assert existing.read_bytes() == b"keep"
    assert not (tmp_path / "résumé_page-0001.jpg").exists()
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_cancel_after_first_page_discards_staged_outputs(pdf, tmp_path):
    token = CancellationToken()

    def cancel(progress):
        if progress.completed == 1:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        PdfImagesConverter(FileFormat.PNG).convert(pdf, tmp_path, {}, cancel, token)
    assert list(tmp_path.iterdir()) == [pdf]


def test_publication_failure_rolls_back_only_job_outputs(pdf, tmp_path, monkeypatch):
    import os

    real_link = os.link

    def link(source, destination):
        if str(destination).endswith("0002.png"):
            Path(destination).write_bytes(b"concurrent writer")
        real_link(source, destination)

    monkeypatch.setattr(os, "link", link)
    with pytest.raises(ConversionError):
        PdfImagesConverter(FileFormat.PNG).convert(
            pdf, tmp_path, {}, lambda _: None, CancellationToken()
        )
    assert not (tmp_path / "résumé_page-0001.png").exists()
    assert (tmp_path / "résumé_page-0002.png").read_bytes() == b"concurrent writer"
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_write_permission_failure_is_actionable(pdf, tmp_path, monkeypatch):
    import local_pdf_toolkit.core.output as output

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(output.tempfile, "TemporaryDirectory", denied)
    with pytest.raises(ConversionError) as error:
        PdfImagesConverter(FileFormat.PNG).convert(
            pdf, tmp_path, {}, lambda _: None, CancellationToken()
        )
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert "permissions" in str(error.value)


def test_encrypted_and_corrupt_rejected(pdf, tmp_path):
    encrypted = tmp_path / "locked.pdf"
    with pymupdf.open(pdf) as doc:
        doc.save(
            encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
    converter = PdfImagesConverter(FileFormat.PNG)
    with pytest.raises(ConversionError) as error:
        converter.validate_input(encrypted)
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED
    corrupt = tmp_path / "fake.pdf"
    for content in (b"not a pdf", b"%PDF-1.4\nbroken"):
        corrupt.write_bytes(content)
        with pytest.raises(ConversionError):
            converter.validate_input(corrupt)


def test_large_page_guard(tmp_path):
    path = tmp_path / "huge.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=10_000, height=10_000)
        doc.save(path)
    with pytest.raises(ConversionError, match="pixels"):
        PdfImagesConverter(FileFormat.PNG).convert(
            path, tmp_path, {}, lambda _: None, CancellationToken()
        )
    assert list(tmp_path.iterdir()) == [path]


def test_100_page_document(tmp_path):
    path = tmp_path / "hundred.pdf"
    with pymupdf.open() as doc:
        for _ in range(100):
            doc.new_page(width=72, height=72)
        doc.save(path)
    result = PdfImagesConverter(FileFormat.JPEG).convert(
        path, tmp_path, {"dpi": 72}, lambda _: None, CancellationToken()
    )
    assert len(result) == 100


def test_scanned_and_rotated_content(tmp_path):
    path = tmp_path / "scan.pdf"
    scan = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    scan.clear_with(255)
    scan.set_rect(pymupdf.IRect(0, 0, 10, 10), (255, 0, 0))
    with pymupdf.open() as doc:
        page = doc.new_page(width=72, height=144)
        page.insert_image(page.rect, stream=scan.tobytes("png"))
        page.set_rotation(90)
        doc.save(path)
    output = PdfImagesConverter(FileFormat.PNG).convert(
        path, tmp_path, {"dpi": 72}, lambda _: None, CancellationToken()
    )
    image = pymupdf.Pixmap(str(output[0]))
    assert (image.width, image.height) == (144, 72)
    assert not image.alpha
    assert len(set(image.samples)) > 1


def test_pdf_detected_by_content_not_extension(pdf):
    renamed = pdf.with_suffix(".bin")
    pdf.rename(renamed)
    assert PdfImagesConverter(FileFormat.JPEG).validate_input(renamed) == FileFormat.PDF
