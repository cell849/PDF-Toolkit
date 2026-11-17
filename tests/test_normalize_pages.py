"""Real PDF geometry, vector appearance and safe publication regression coverage."""

import hashlib

import pymupdf
import pytest

from local_pdf_toolkit.converters.normalize_pages import (
    MAX_PAGE_POINTS,
    PAPER_SIZES_MM,
    POINTS_PER_MM,
    PdfNormalizePagesConverter,
    normalize_page_converters,
)
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.pdf"
    with pymupdf.open() as document:
        for index, dimensions in enumerate(((200, 100), (100, 200), (200, 100)), 1):
            page = document.new_page(width=dimensions[0], height=dimensions[1])
            for bounds, color in (
                ((0, 0, dimensions[0] / 4, dimensions[1]), (1, 0, 0)),
                ((dimensions[0] / 4, 0, 3 * dimensions[0] / 4, dimensions[1]), (0, 1, 0)),
                ((3 * dimensions[0] / 4, 0, dimensions[0], dimensions[1]), (0, 0, 1)),
            ):
                page.draw_rect(bounds, color=None, fill=color)
            page.insert_text((30, 40), f"Page {index}", fontsize=8)
        document.set_metadata({"title": "Synthetic fixture"})
        document.save(path)
    return path


def convert(source, output, options=None, progress=None, token=None):
    return PdfNormalizePagesConverter().convert(
        source, output, options or {}, progress or (lambda _: None), token or CancellationToken()
    )


def test_spec_and_factory():
    (converter,) = normalize_page_converters()
    assert converter.spec.operation_id == "pdf.normalize_pages"
    assert converter.spec.input_formats == converter.spec.output_formats == (FileFormat.PDF,)
    assert len(PAPER_SIZES_MM) == 33
    assert PAPER_SIZES_MM["A4"] == (210, 297)
    assert PAPER_SIZES_MM["B0"] == (1000, 1414)
    assert PAPER_SIZES_MM["C10"] == (28, 40)
    assert set(PAPER_SIZES_MM) == {f"{series}{i}" for series in "ABC" for i in range(11)}
    for series in "ABC":
        for i in range(1, 11):
            previous = PAPER_SIZES_MM[f"{series}{i - 1}"]
            current = PAPER_SIZES_MM[f"{series}{i}"]
            assert abs(current[0] - previous[1] / 2) <= 1
            assert abs(current[1] - previous[0]) <= 1
    assert "links" in " ".join(converter.spec.limitations)


def test_selected_pages_auto_orientation_preserve_original_and_vectors(source, tmp_path):
    digest = hashlib.sha256(source.read_bytes()).digest()
    updates = []
    (result,) = convert(source, tmp_path, {"pages": "2-3"}, progress=updates.append)
    with pymupdf.open(source) as original, pymupdf.open(result) as document:
        assert document[0].rect == original[0].rect
        assert document[0].get_pixmap().samples == original[0].get_pixmap().samples
        assert document[1].rect.width == pytest.approx(210 * POINTS_PER_MM, abs=0.001)
        assert document[1].rect.height == pytest.approx(297 * POINTS_PER_MM, abs=0.001)
        assert document[2].rect.width == pytest.approx(297 * POINTS_PER_MM, abs=0.001)
        assert document[2].rect.height == pytest.approx(210 * POINTS_PER_MM, abs=0.001)
        for index, page in enumerate(document, 1):
            assert f"Page {index}" in page.get_text()
            assert len(page.get_drawings()) == 3
            assert page.get_images() == []
        assert document.metadata["title"] == "Synthetic fixture"
    assert hashlib.sha256(source.read_bytes()).digest() == digest
    assert updates[0].completed == 0
    assert updates[-1].completed == updates[-1].total == 3


@pytest.mark.parametrize(
    "paper, mm",
    [
        ("A0", (841, 1189)),
        ("A10", (26, 37)),
        ("B0", (1000, 1414)),
        ("C10", (28, 40)),
        ("Letter", (215.9, 279.4)),
        ("Tabloid", (279.4, 431.8)),
    ],
)
def test_paper_families_extremes_and_us_sizes_have_expected_dimensions(source, tmp_path, paper, mm):
    (result,) = convert(source, tmp_path, {"paper": paper, "orientation": "portrait"})
    with pymupdf.open(result) as document:
        assert tuple(document[0].rect)[2:] == pytest.approx(
            tuple(dimension * 72 / 25.4 for dimension in mm), abs=0.001
        )


@pytest.mark.parametrize(
    "orientation, expected", [("portrait", (100, 200)), ("landscape", (200, 100))]
)
def test_explicit_orientation_with_custom_dimensions(source, tmp_path, orientation, expected):
    (result,) = convert(
        source,
        tmp_path,
        {
            "paper": "custom",
            "custom_width": 200,
            "custom_height": 100,
            "units": "pt",
            "orientation": orientation,
        },
    )
    with pymupdf.open(result) as document:
        for page in document:
            assert (page.rect.width, page.rect.height) == expected


@pytest.mark.parametrize(
    "units, width, height", [("pt", 144, 216), ("in", 2, 3), ("mm", 50.8, 76.2), ("cm", 5.08, 7.62)]
)
def test_custom_units(source, tmp_path, units, width, height):
    (result,) = convert(
        source,
        tmp_path,
        {
            "paper": "custom",
            "custom_width": width,
            "custom_height": height,
            "units": units,
            "orientation": "portrait",
        },
    )
    with pymupdf.open(result) as document:
        assert (document[0].rect.width, document[0].rect.height) == pytest.approx((144, 216))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("cropped", [False, True])
def test_rotation_and_crop_keep_rendered_appearance(source, tmp_path, rotation, cropped):
    edited = tmp_path / "edited.pdf"
    with pymupdf.open(source) as document:
        if cropped:
            document[0].set_cropbox(pymupdf.Rect(10, 10, 180, 90))
        document[0].set_rotation(rotation)
        dimensions = document[0].rect.width, document[0].rect.height
        document.save(edited)
    (result,) = convert(
        edited,
        tmp_path,
        {
            "pages": "1",
            "paper": "custom",
            "units": "pt",
            "custom_width": dimensions[0],
            "custom_height": dimensions[1],
        },
    )
    with pymupdf.open(edited) as original, pymupdf.open(result) as normalized:
        expected = original[0].get_pixmap()
        actual = normalized[0].get_pixmap()
        assert (actual.width, actual.height) == (expected.width, expected.height)
        # Check real raster content well away from antialiased text/shape boundaries.
        for x in (10, actual.width // 3, actual.width - 10):
            for y in (10, actual.height // 3, actual.height - 10):
                assert actual.pixel(x, y) == expected.pixel(x, y)
        assert "Page 1" in normalized[0].get_text()


@pytest.mark.parametrize("fit", ["contain", "cover"])
def test_centered_fit_keeps_aspect_ratio_and_white_margins(source, tmp_path, fit):
    (result,) = convert(
        source,
        tmp_path,
        {
            "pages": "1",
            "paper": "custom",
            "units": "pt",
            "custom_width": 100,
            "custom_height": 100,
            "margin_mm": 10 / POINTS_PER_MM,
            "fit": fit,
        },
    )
    with pymupdf.open(result) as document:
        pixmap = document[0].get_pixmap()
        assert pixmap.pixel(5, 50) == pixmap.pixel(50, 5) == (255, 255, 255)
        assert pixmap.pixel(50, 60) == (0, 255, 0)
        if fit == "contain":
            assert pixmap.pixel(50, 20) == (255, 255, 255)
            assert pixmap.pixel(20, 50) == (255, 0, 0)
            assert pixmap.pixel(80, 50) == (0, 0, 255)
        else:
            assert pixmap.pixel(50, 20) == (0, 255, 0)
            assert pixmap.pixel(20, 50) == pixmap.pixel(80, 50) == (0, 255, 0)


def test_selected_appearances_baked_unselected_interactivity_and_links_copied(source, tmp_path):
    annotated = tmp_path / "annotated.pdf"
    with pymupdf.open(source) as document:
        for index in (0, 1):
            page = document[index]
            annotation = page.add_rect_annot(pymupdf.Rect(5, 5, 60, 60))
            annotation.set_colors(stroke=(1, 0, 1))
            annotation.set_border(width=3)
            annotation.update()
            widget = pymupdf.Widget()
            widget.field_name = f"field{index}"
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.field_value = "Visible field"
            widget.rect = pymupdf.Rect(20, 60, 95, 90)
            page.add_widget(widget)
            page.insert_link(
                {
                    "kind": pymupdf.LINK_URI,
                    "from": pymupdf.Rect(0, 0, 10, 10),
                    "uri": "https://example.invalid/",
                }
            )
            page.insert_link(
                {"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(10, 0, 20, 10), "page": 2}
            )
            page.insert_link(
                {"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(20, 0, 30, 10), "page": index}
            )
        document.save(annotated)
    (result,) = convert(
        annotated,
        tmp_path,
        {"pages": "1", "paper": "custom", "units": "pt", "custom_width": 200, "custom_height": 100},
    )
    with pymupdf.open(result) as document, pymupdf.open(annotated) as original:
        assert list(document[0].annots()) == list(document[0].widgets()) == []
        assert document[0].get_links() == []
        assert "Visible field" in document[0].get_text()
        assert document[0].get_pixmap().pixel(5, 10) == original[0].get_pixmap().pixel(5, 10)
        assert len(list(document[1].annots())) == len(list(document[1].widgets())) == 1
        assert len(document[1].get_links()) == 3
        assert sorted(
            link["page"] for link in document[1].get_links() if link["kind"] == pymupdf.LINK_GOTO
        ) == [1, 2]
        assert len(list(original[0].annots())) == len(list(original[0].widgets())) == 1


@pytest.mark.parametrize(
    "options",
    [
        {"bogus": 1},
        {"paper": "A11"},
        {"orientation": "diagonal"},
        {"fit": "stretch"},
        {"units": "pixels"},
        {"pages": "4"},
        {"pages": "2-1"},
        {"pages": 1},
        {"margin_mm": -1},
        {"margin_mm": 101},
        {"paper": "A10", "margin_mm": 20},
        {"custom_width": True},
        {"custom_width": float("nan")},
        {"custom_height": float("inf")},
        {"custom_width": 10**1000},
        {"paper": "custom", "custom_width": 0},
        {"paper": "custom", "units": "pt", "custom_width": MAX_PAGE_POINTS + 1},
        {"paper": "custom", "units": "in", "custom_width": 201},
        {"paper": "custom", "units": "pt", "custom_width": 10_000, "custom_height": 10_000},
    ],
)
def test_invalid_options_leave_nothing_published(source, tmp_path, options):
    before = source.read_bytes()
    with pytest.raises(ConversionError) as error:
        convert(source, tmp_path, options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS
    assert source.read_bytes() == before
    assert list(tmp_path.glob("*.pdf")) == [source]
    assert list(tmp_path.glob(".pdf-toolkit-*")) == []


def test_empty_page_supported(tmp_path):
    source = tmp_path / "blank.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(source)
    (result,) = convert(source, tmp_path)
    with pymupdf.open(result) as document:
        assert document[0].get_text() == ""
        assert document[0].get_pixmap().pixel(10, 10) == (255, 255, 255)


@pytest.mark.parametrize("normalize_destination", [False, True])
def test_restored_internal_link_geometry_on_rotated_pages(source, tmp_path, normalize_destination):
    linked = tmp_path / "linked.pdf"
    with pymupdf.open(source) as document:
        document[1].set_rotation(90)
        document[2].set_rotation(270)
        document[1].insert_link(
            {
                "kind": pymupdf.LINK_GOTO,
                "page": 2,
                "from": pymupdf.Rect(10, 20, 30, 40),
                "to": pymupdf.Point(5, 15),
            }
        )
        document.save(linked)
    (result,) = convert(
        linked,
        tmp_path,
        {
            "pages": "1,3" if normalize_destination else "1",
            "paper": "custom",
            "units": "pt",
            "custom_width": 200,
            "custom_height": 400,
        },
    )
    with pymupdf.open(linked) as original, pymupdf.open(result) as normalized:
        before = original[1].get_links()[0]
        after = normalized[1].get_links()[0]
        assert tuple(after["from"]) == pytest.approx(tuple(before["from"]))
        expected = before["to"] * (2 if normalize_destination else 1)
        assert tuple(after["to"]) == pytest.approx(tuple(expected))


@pytest.mark.parametrize("owner_only", [False, True])
def test_encrypted_input_rejected(source, tmp_path, owner_only):
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open(source) as document:
        document.save(
            encrypted,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="" if owner_only else "secret",
        )
    with pytest.raises(ConversionError) as error:
        convert(encrypted, tmp_path)
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED
    assert not (tmp_path / "encrypted_normalized.pdf").exists()


def test_oversized_source_and_corrupt_input_rejected(tmp_path):
    source = tmp_path / "oversized.pdf"
    with pymupdf.open() as document:
        document.new_page(width=10_000, height=10_000)
        document.save(source)
    with pytest.raises(ConversionError) as error:
        convert(source, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT
    source.write_bytes(b"%PDF-1.7\ninvalid")
    with pytest.raises(ConversionError) as error:
        convert(source, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT


def test_no_overwrite_and_cancellation_cleanup(source, tmp_path):
    destination = tmp_path / "source_normalized.pdf"
    destination.write_bytes(b"existing")
    with pytest.raises(ConversionError) as error:
        convert(source, tmp_path)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert destination.read_bytes() == b"existing"
    destination.unlink()
    token = CancellationToken()

    def cancel(progress):
        if progress.completed == 1:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        convert(source, tmp_path, progress=cancel, token=token)
    assert not destination.exists()
    assert list(tmp_path.glob(".pdf-toolkit-*")) == []
