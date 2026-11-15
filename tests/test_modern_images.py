"""Real codec round trips for phone-photo cleanup and preview integration."""

import io
import json

import pytest
from PIL import Image, ImageOps

from local_pdf_toolkit.converters.image_metadata import ImageMetadataConverter, clean_image_bytes
from local_pdf_toolkit.converters.images import FORMATS, ImageConverter
from local_pdf_toolkit.converters.inspector import MetadataInspector
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.formats import FileFormat


@pytest.mark.parametrize("kind", ["AVIF", "HEIF"])
def test_modern_photo_cleanup_and_conversion(tmp_path, kind):
    if kind not in FORMATS:
        pytest.skip(f"Optional {kind} codec is not installed")
    source = tmp_path / "private.photo"
    exif = Image.Exif()
    exif[315] = "Private owner"
    exif[274] = 6
    image = Image.new("RGB", (40, 60), "red")
    image.save(source, format=kind, exif=exif, xmp=b"<private>Private location</private>")
    original = source.read_bytes()
    with Image.open(source) as decoded:
        expected_size = ImageOps.exif_transpose(decoded).size
    token = CancellationToken()
    cleaned, report = ImageMetadataConverter().convert(source, tmp_path, {}, lambda _: None, token)
    with Image.open(cleaned) as result:
        assert result.format == kind
        assert result.size == expected_size
        assert not result.getexif()
        assert not result.info.get("xmp")
        assert not result.info.get("icc_profile")
    assert b"Private" not in cleaned.read_bytes()
    assert "Private" not in report.read_text()
    (comparison,) = MetadataInspector().convert(
        (source, cleaned), tmp_path, {}, lambda _: None, token
    )
    rows = json.loads(comparison.read_text())["inspection"]
    assert rows[0]["fields_detected"] > rows[1]["fields_detected"]
    (png,) = ImageConverter(FileFormat.PNG).convert(source, tmp_path, {}, lambda _: None, token)
    with Image.open(png) as result:
        assert result.size == expected_size
    assert source.read_bytes() == original


@pytest.mark.parametrize("kind", ["AVIF", "HEIF"])
def test_modern_alpha_survives_cleanup(kind):
    if kind not in FORMATS:
        pytest.skip(f"Optional {kind} codec is not installed")
    encoded = io.BytesIO()
    Image.new("RGBA", (16, 16), (30, 80, 120, 64)).save(encoded, format=kind)
    cleaned = clean_image_bytes(encoded.getvalue())
    with Image.open(io.BytesIO(cleaned)) as result:
        assert "A" in result.getbands()
        assert abs(result.getpixel((5, 5))[3] - 64) <= 2
