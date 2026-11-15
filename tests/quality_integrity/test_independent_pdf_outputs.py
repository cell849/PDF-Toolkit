"""Cross-engine privacy, redaction, page order, and lossless content checks."""

import json

import pytest

from local_pdf_toolkit.converters.compress import PdfCompressConverter
from local_pdf_toolkit.converters.pdf_metadata import PdfMetadataConverter
from local_pdf_toolkit.converters.pdf_tools import PdfToolConverter
from local_pdf_toolkit.converters.redaction import PdfRedactionConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionError

from .independent_pdf import extract_text, poppler, render, sha256, write_pdf


def convert(converter, source, output, options=None):
    return converter.convert(source, output, options or {}, lambda _: None, CancellationToken())


def assert_flat_areas_match(original, result):
    """Compare solid-color interiors, allowing engine-dependent boundary interpolation."""
    assert original.size == result.size
    expected = original.load()
    actual = result.load()
    compared = 0
    for y in range(2, original.height - 2):
        for x in range(2, original.width - 2):
            color = expected[x, y]
            if all(expected[x + dx, y + dy] == color for dx in (-2, 0, 2) for dy in (-2, 0, 2)):
                assert actual[x, y] == color
                compared += 1
    assert compared > (original.width - 4) * (original.height - 4) * 0.7


def assert_no_nonvisual_secrets(path):
    assert not extract_text(path).strip()
    assert b"0 embedded files" in poppler("pdfdetach", "-list", path)
    expanded = poppler("qpdf", "--qdf", "--object-streams=disable", path, "-")
    for forbidden in (
        b"SECRET-",
        b"/JavaScript",
        b"/OpenAction",
        b"/EmbeddedFile",
        b"/AcroForm",
        b"/Metadata",
        b"/Annots",
    ):
        assert forbidden not in expanded
    information = poppler("pdfinfo", path)
    assert b"Author:" not in information
    assert b"Title:" not in information


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [False, True])
def test_redaction_independent_renderer_has_opaque_display_space_mask(tmp_path, rotation, crop):
    # Exact visual oracle uses solid vector colors. Hidden identifiers exercise text
    # removal without assuming that Poppler and MuPDF use identical font antialiasing.
    source = write_pdf(
        tmp_path / "SECRET-PATH.pdf", rotation=rotation, crop=crop, text_visible=False
    )
    before = sha256(source)
    source_text = extract_text(source)
    assert "SECRET-VISIBLE" in source_text and "SECRET-HIDDEN" in source_text
    assert "PAGE-2" in source_text
    assert b"1 embedded files" in poppler("pdfdetach", "-list", source)
    output = tmp_path / "output"
    output.mkdir()
    region = {"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.65, "y1": 0.45}
    result, report = convert(
        PdfRedactionConverter(),
        source,
        output,
        {"dpi": 72, "regions": json.dumps([region]), "source_sha256": before},
    )
    assert_no_nonvisual_secrets(result)
    with (
        render(source, tmp_path / "original") as original,
        render(result, tmp_path / "redacted") as redacted,
    ):
        assert redacted.size == original.size
        x, y = int(redacted.width * 0.3), int(redacted.height * 0.25)
        assert original.getpixel((x, y)) != (0, 0, 0)
        assert redacted.getpixel((x, y)) == (0, 0, 0)
        with redacted.crop(
            (
                int(redacted.width * 0.11),
                int(redacted.height * 0.11),
                int(redacted.width * 0.64),
                int(redacted.height * 0.44),
            )
        ) as mask:
            assert mask.getextrema() == ((0, 0), (0, 0), (0, 0))
        # A colored rectangle strictly below/right of the marked area survives.
        box = (
            int(original.width * 0.75),
            int(original.height * 0.65),
            int(original.width * 0.85),
            int(original.height * 0.75),
        )
        with original.crop(box) as expected, redacted.crop(box) as actual:
            assert_flat_areas_match(expected, actual)
    with (
        render(source, tmp_path / "original-second", page=2) as original,
        render(result, tmp_path / "redacted-second", page=2) as redacted,
    ):
        assert_flat_areas_match(original, redacted)
    report_text = report.read_text()
    assert "SECRET" not in report_text and before not in report_text and "x0" not in report_text
    assert all("SECRET" not in path.name for path in (result, report))
    assert sha256(source) == before
    assert set(output.iterdir()) == {result, report}


def test_flattened_privacy_copy_drops_hidden_objects_and_keeps_visible_color(tmp_path):
    source = write_pdf(tmp_path / "source.pdf")
    before = sha256(source)
    result, report = convert(PdfMetadataConverter(), source, tmp_path, {"dpi": 72})
    assert_no_nonvisual_secrets(result)
    with (
        render(source, tmp_path / "original") as original,
        render(result, tmp_path / "cleaned") as cleaned,
    ):
        # Compare solid areas; engines can antialias font outlines differently.
        for point in ((5, 5), (35, 60), (100, 270)):
            assert original.getpixel(point) == cleaned.getpixel(point)
    assert "SECRET" not in report.read_text()
    assert sha256(source) == before


def test_lossless_compression_keeps_independently_extracted_text_and_all_pages(tmp_path):
    source = write_pdf(tmp_path / "source.pdf", pages=3)
    before = sha256(source)
    expected = extract_text(source)
    (result,) = convert(PdfCompressConverter(), source, tmp_path)
    assert extract_text(result) == expected
    poppler("qpdf", "--check", result)
    assert sha256(source) == before


@pytest.mark.parametrize(
    "operation,options,expected",
    [
        ("reorder", {"order": "3,1-2"}, [3, 1, 2]),
        ("extract", {"pages": "3,1"}, [1, 3]),
        ("delete", {"pages": "2"}, [1, 3]),
    ],
)
def test_page_operations_preserve_independent_page_identifiers(
    tmp_path, operation, options, expected
):
    source = write_pdf(tmp_path / "source.pdf", pages=3)
    before = sha256(source)
    (result,) = convert(PdfToolConverter(operation), source, tmp_path, options)
    text = extract_text(result)
    assert [
        next(n for n in (1, 2, 3) if f"PAGE-{n}" in page)
        for page in text.split("\f")
        if page.strip()
    ] == expected
    poppler("qpdf", "--check", result)
    assert sha256(source) == before


def test_split_second_publication_collision_keeps_foreign_file_and_original(tmp_path, monkeypatch):
    from pathlib import Path

    from local_pdf_toolkit.core import output as output_module

    source = write_pdf(tmp_path / "source.pdf", pages=3)
    before = sha256(source)
    output = tmp_path / "output"
    output.mkdir()
    real_link = output_module.os.link

    def collide_second(source_path, destination):
        if Path(destination).name.endswith("0002.pdf"):
            Path(destination).write_bytes(b"foreign file bytes")
        real_link(source_path, destination)

    monkeypatch.setattr(output_module.os, "link", collide_second)
    with pytest.raises(ConversionError):
        convert(PdfToolConverter("split"), source, output)
    assert [path.name for path in output.iterdir()] == ["source_page-0002.pdf"]
    assert (output / "source_page-0002.pdf").read_bytes() == b"foreign file bytes"
    assert sha256(source) == before
