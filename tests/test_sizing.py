"""Size units, explicit resizing and preservation of selected raster dimensions."""

import hashlib
import json
from decimal import Decimal

import pymupdf
import pytest
from PIL import Image

from local_pdf_toolkit.converters.compress import PdfCompressConverter
from local_pdf_toolkit.converters.images import ImageConverter
from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.converters.preview import PreviewConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.sizing import target_bytes


def run(converter, source, output, options=None):
    output.mkdir(exist_ok=True)
    return converter.convert(source, output, options or {}, lambda _: None, CancellationToken())


@pytest.mark.parametrize(
    "unit,value,expected",
    [
        ("KB", 1.25, 1250),
        ("MB", 0.00125, 1250),
        ("KiB", 1.25, 1280),
        ("MiB", 0.00125, 1310),
        ("percent", 33.3, 333),
    ],
)
def test_target_units_floor_bytes(unit, value, expected):
    assert target_bytes({"target_value": value, "target_unit": unit}, 1001) == expected


def test_percent_uses_decimal_input_before_flooring():
    # Binary float multiplication would round this just below 575 bytes.
    assert target_bytes({"target_value": 57.5, "target_unit": "percent"}, 1000) == 575
    assert target_bytes({}, 1000) == 0
    assert target_bytes({"target_kib": 3}, 1000) == 3072


@pytest.mark.parametrize(
    "options",
    [
        {"target_value": float("nan")},
        {"target_value": float("inf")},
        {"target_value": -1},
        {"target_value": True},
        {"target_value": "3"},
        {"target_value": 10**1000},
        {"target_value": Decimal("1")},
        {"target_value": 101, "target_unit": "percent"},
        {"target_unit": "GB"},
        {"target_value": 2, "target_kib": 1},
        {"target_kib": 1.5},
        {"allow_downscale": 1},
    ],
)
@pytest.mark.parametrize("converter", [ImageConverter(FileFormat.PNG), PdfCompressConverter()])
def test_invalid_size_options_rejected(options, converter):
    with pytest.raises(ConversionError) as error:
        converter.validate_options(options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_sub_byte_target_is_not_treated_as_disabled():
    with pytest.raises(ConversionError, match="one byte"):
        target_bytes({"target_value": 0.01, "target_unit": "percent"}, 1)


@pytest.fixture
def noise(tmp_path):
    source = tmp_path / "noise.png"
    with Image.effect_noise((300, 200), 100) as image:
        image.save(source)
    return source


@pytest.mark.parametrize(
    "options,size",
    [
        ({"resize_percent": 50}, (150, 100)),
        ({"resize_percent": 50, "width": 75}, (75, 50)),
        ({"resize_percent": 50, "height": 30}, (45, 30)),
        ({"width": 2000, "height": 2000}, (300, 200)),
    ],
)
def test_resize_percent_and_maxima_preserve_aspect(noise, tmp_path, options, size):
    before = hashlib.sha256(noise.read_bytes()).digest()
    (output,) = run(ImageConverter(FileFormat.PNG), noise, tmp_path / "out", options)
    with Image.open(output) as image:
        assert image.size == size
    assert hashlib.sha256(noise.read_bytes()).digest() == before


@pytest.mark.parametrize("percent", [0, 101, 1.5, True])
def test_percent_cannot_enlarge_or_use_noninteger(percent):
    with pytest.raises(ConversionError):
        ImageConverter(FileFormat.PNG).validate_options({"resize_percent": percent})


def test_default_image_target_preserves_resolution_and_fails_cleanly(noise, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(ConversionError, match="Target size"):
        run(ImageConverter(FileFormat.PNG), noise, out, {"target_value": 1, "target_unit": "KiB"})
    assert list(out.iterdir()) == []


@pytest.mark.parametrize("unit,value", [("KB", 1.5), ("percent", 10)])
def test_explicit_image_downscale_meets_target(noise, tmp_path, unit, value):
    options = {"target_value": value, "target_unit": unit, "allow_downscale": True}
    (output,) = run(ImageConverter(FileFormat.PNG), noise, tmp_path / "out", options)
    assert output.stat().st_size <= target_bytes(options, noise.stat().st_size)
    with Image.open(output) as image:
        assert image.width < 300 and image.height < 200


def test_quality_target_keeps_selected_image_dimensions(noise, tmp_path):
    (output,) = run(
        ImageConverter(FileFormat.JPEG),
        noise,
        tmp_path / "out",
        {"target_value": 30, "target_unit": "KB", "resize_percent": 80},
    )
    assert output.stat().st_size <= 30000
    with Image.open(output) as image:
        assert image.size == (240, 160)


@pytest.fixture
def scan(noise, tmp_path):
    source = tmp_path / "scan.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=72, height=48)
        page.insert_image(page.rect, filename=str(noise))
        doc.save(source)
    return source


@pytest.mark.parametrize("converter", [PdfImagesConverter(FileFormat.PNG), PdfCompressConverter()])
@pytest.mark.parametrize("dpi", [9, 1201, 276.0, True, float("nan")])
def test_dpi_boundaries_and_integer_type(converter, dpi):
    with pytest.raises(ConversionError):
        converter.validate_options({"dpi": dpi})


def test_custom_dpi_pdf_export_and_compression(scan, tmp_path):
    (raster,) = run(PdfImagesConverter(FileFormat.PNG), scan, tmp_path / "raster", {"dpi": 276})
    with Image.open(raster) as image:
        assert image.size == (276, 184)
    (compressed,) = run(
        PdfCompressConverter(), scan, tmp_path / "compressed", {"mode": "rasterized", "dpi": 276}
    )
    with pymupdf.open(compressed) as doc:
        image = doc[0].get_images()[0]
        assert image[2:4] == (276, 184)
        assert (doc[0].rect.width, doc[0].rect.height) == (72, 48)


def test_pdf_target_requires_explicit_downscale(scan, tmp_path):
    options = {"mode": "rasterized", "dpi": 276, "target_value": 8, "target_unit": "KiB"}
    preserved = tmp_path / "preserved"
    with pytest.raises(ConversionError, match="Target size"):
        run(PdfCompressConverter(), scan, preserved, options)
    assert list(preserved.iterdir()) == []
    (output,) = run(
        PdfCompressConverter(), scan, tmp_path / "smaller", {**options, "allow_downscale": True}
    )
    assert output.stat().st_size <= 8192
    with pymupdf.open(output) as doc:
        image = doc[0].get_images()[0]
        assert image[2] < 276 and image[3] < 184


@pytest.mark.parametrize("converter", [PdfImagesConverter(FileFormat.PNG), PdfCompressConverter()])
def test_custom_dpi_checks_ceil_pixel_limit_before_render(tmp_path, monkeypatch, converter):
    source = tmp_path / "huge.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=2000, height=2000)
        doc.save(source)

    def no_allocation(*args, **kwargs):
        pytest.fail("Oversized custom-DPI raster must be rejected before allocation")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", no_allocation)
    with pytest.raises(ConversionError, match="pixels"):
        run(
            converter,
            source,
            tmp_path / "out",
            {
                "dpi": 1200,
                **({"mode": "rasterized"} if isinstance(converter, PdfCompressConverter) else {}),
            },
        )
    assert list((tmp_path / "out").iterdir()) == []


def test_preview_reports_native_dimensions_and_original_size(scan, noise, tmp_path):
    for source, unit, dimensions in [(scan, "pt", (72, 48)), (noise, "px", (300, 200))]:
        paths = run(PreviewConverter(), source, tmp_path / (unit + "-preview"))
        info = json.loads(next(path for path in paths if path.suffix == ".json").read_text())
        assert info["native_unit"] == unit
        assert (info["native_width"], info["native_height"]) == dimensions
        assert info["source_bytes"] == source.stat().st_size
        assert max(info["width"], info["height"]) <= 1400
