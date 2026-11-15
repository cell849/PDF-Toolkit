"""Synthetic metadata-bearing fixtures; no personal files are committed."""

import io
import json

import pytest
from PIL import Image, PngImagePlugin, TiffImagePlugin

from local_pdf_toolkit.converters.image_metadata import (
    ImageMetadataConverter,
    clean_image_bytes,
)
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError


def encoded(kind, mode="RGB", **kwargs):
    image = Image.new(mode, (20, 10), "red")
    buffer = io.BytesIO()
    image.save(buffer, format=kind, **kwargs)
    image.close()
    return buffer.getvalue()


def opened(data):
    return Image.open(io.BytesIO(data))


def exif():
    result = Image.Exif()
    result[315] = "Private Owner"
    result[306] = "2025:01:01 12:01:02"
    result[34853] = {1: "N", 2: (1.0, 2.0, 3.0), 3: "E", 4: (4.0, 5.0, 6.0)}
    return result


def test_jpeg_exif_gps_comments_and_trailing_data_removed():
    source = encoded("JPEG", exif=exif(), icc_profile=b"private profile")
    # COM segment containing a comment, then a non-image trailer.
    comment = b"Private comment"
    source = source[:2] + b"\xff\xfe" + (len(comment) + 2).to_bytes(2, "big") + comment + source[2:]
    source += b"private trailing data"
    result = clean_image_bytes(source)
    with opened(result) as image:
        assert image.format == "JPEG"
        assert not image.getexif()
        assert "comment" not in image.info and "icc_profile" not in image.info
    assert result.endswith(b"\xff\xd9")


def test_exif_orientation_is_applied_before_removal():
    metadata = exif()
    metadata[274] = 6
    result = clean_image_bytes(encoded("JPEG", exif=metadata))
    with opened(result) as image:
        assert image.size == (10, 20)
        assert not image.getexif()


def test_png_text_exif_xmp_icc_and_alpha():
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Author", "Private owner")
    metadata.add_itxt("XML:com.adobe.xmp", "Private XMP")
    source = encoded("PNG", "RGBA", pnginfo=metadata, exif=exif(), icc_profile=b"private profile")
    result = clean_image_bytes(source)
    with opened(result) as image:
        assert image.size == (20, 10)
        assert image.mode == "RGBA"
        assert not image.getexif()
        assert not image.info


def test_png_transparent_pixels_preserved():
    image = Image.new("RGBA", (3, 4), (10, 20, 30, 0))
    source = io.BytesIO()
    image.save(source, format="PNG")
    with opened(clean_image_bytes(source.getvalue())) as cleaned:
        assert cleaned.getpixel((1, 1)) == (10, 20, 30, 0)


def test_webp_exif_xmp_icc_removed():
    source = encoded("WEBP", exif=exif(), xmp=b"private XMP", icc_profile=b"private ICC")
    with opened(clean_image_bytes(source)) as image:
        assert image.format == "WEBP"
        assert not image.getexif()
        assert not {"exif", "xmp", "icc_profile"}.intersection(image.info)


def test_tiff_descriptive_ifd_tags_are_removed():
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[270] = "Private description"
    tags[305] = "Personal software name"
    tags[315] = "Private owner"
    tags[306] = "2025:01:01 00:00:00"
    source = encoded("TIFF", tiffinfo=tags)
    with opened(clean_image_bytes(source)) as image:
        assert image.format == "TIFF"
        assert not {270, 305, 315, 306}.intersection(image.tag_v2)
        assert image.getpixel((0, 0)) == (255, 0, 0)


def test_gif_comment_removed_preserving_transparency():
    image = Image.new("RGBA", (4, 4), (255, 0, 0, 0))
    source = io.BytesIO()
    image.save(source, format="GIF", comment=b"Private owner")
    with opened(clean_image_bytes(source.getvalue())) as result:
        assert result.format == "GIF"
        assert "comment" not in result.info
        assert result.convert("RGBA").getpixel((1, 1))[3] == 0


@pytest.mark.parametrize("kind", ["JPEG", "PNG", "WEBP", "TIFF", "BMP", "GIF"])
def test_preserves_recognized_container_and_dimensions(kind):
    with opened(clean_image_bytes(encoded(kind))) as image:
        assert image.format == kind
        assert image.size == (20, 10)


def test_animated_gif_and_multipage_tiff_rejected():
    for kind in ("GIF", "TIFF"):
        output = io.BytesIO()
        Image.new("RGB", (3, 3), "red").save(
            output, format=kind, save_all=True, append_images=[Image.new("RGB", (3, 3), "blue")]
        )
        with pytest.raises(ConversionError, match="multi-page"):
            clean_image_bytes(output.getvalue())


@pytest.mark.parametrize("data", [b"", b"not image", b"%PDF-1.4\n", b"\x89PNG\r\n"])
def test_unsupported_and_corrupt_rejected(data):
    with pytest.raises(ConversionError):
        clean_image_bytes(data)


def test_pixel_and_byte_limits(monkeypatch):
    from local_pdf_toolkit.converters import image_metadata

    data = encoded("PNG")
    monkeypatch.setattr(image_metadata, "MAX_PIXELS", 100)
    with pytest.raises(ConversionError, match="pixel"):
        clean_image_bytes(data)
    monkeypatch.setattr(image_metadata, "MAX_BYTES", 1)
    with pytest.raises(ConversionError, match="512 MiB"):
        clean_image_bytes(data)


def test_converter_source_neutral_output_and_report(tmp_path):
    source = tmp_path / "Private Owner Photo.jpg"
    contents = encoded("JPEG", exif=exif())
    source.write_bytes(contents)
    converter = ImageMetadataConverter()
    updates = []
    paths = converter.convert(source, tmp_path, {}, updates.append, CancellationToken())
    assert len(paths) == 2
    assert all("Private" not in path.name for path in paths)
    assert paths[0].name.startswith("clean-image-")
    assert source.read_bytes() == contents
    report = json.loads(paths[1].read_text())
    assert report["format"] == "JPEG" and report["width"] == 20
    assert "Private" not in paths[1].read_text()
    assert updates[-1].completed == updates[-1].total == 1
    assert not list(tmp_path.glob(".pdf-toolkit-*"))
    next_paths = converter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    assert next_paths[0] != paths[0]


def test_precancel_does_not_read_source(tmp_path):
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConversionCancelled):
        ImageMetadataConverter().convert(
            tmp_path / "missing.png", tmp_path, {}, lambda _: None, token
        )
    assert not list(tmp_path.iterdir())


def test_cancel_after_encoding_publishes_nothing(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(encoded("PNG"))
    token = CancellationToken()

    def progress(_):
        token.cancel()

    with pytest.raises(ConversionCancelled):
        ImageMetadataConverter().convert(source, tmp_path, {}, progress, token)
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize(
    "kind,mode,value", [("PNG", "I;16", 2048), ("TIFF", "I;16", 8192), ("TIFF", "F", 1.25)]
)
def test_high_bit_depth_samples_are_not_clipped(kind, mode, value):
    image = Image.new(mode, (10, 10), value)
    buffer = io.BytesIO()
    image.save(buffer, format=kind)
    with opened(clean_image_bytes(buffer.getvalue())) as result:
        assert result.getpixel((0, 0)) == value
