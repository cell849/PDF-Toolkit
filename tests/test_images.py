import hashlib

import pymupdf
import pytest
from PIL import Image

from local_pdf_toolkit.converters.compress import PdfCompressConverter
from local_pdf_toolkit.converters.images import ImageConverter, ImagesPdfConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError
from local_pdf_toolkit.core.formats import FileFormat


def run(converter, source, out, options=None, progress=lambda _: None, token=None):
    return converter.convert(source, out, options or {}, progress, token or CancellationToken())


@pytest.fixture
def images(tmp_path):
    paths = []
    for color, size in [("red", (120, 240)), ("blue", (240, 120))]:
        path = tmp_path / f"{color}.png"
        Image.new("RGB", size, color).save(path)
        paths.append(path)
    return tuple(paths)


def test_images_to_pdf_keeps_order_and_sources(images, tmp_path):
    hashes = [hashlib.sha256(p.read_bytes()).digest() for p in images]
    paths = run(ImagesPdfConverter(), images[::-1], tmp_path)
    with pymupdf.open(paths[0]) as doc:
        assert len(doc) == 2
        assert (doc[0].rect.width, doc[0].rect.height) == (180, 90)
        assert doc[0].get_pixmap().pixel(80, 40)[:3] == (0, 0, 255)
    assert hashes == [hashlib.sha256(p.read_bytes()).digest() for p in images]


@pytest.mark.parametrize(
    "format", [FileFormat.JPEG, FileFormat.PNG, FileFormat.WEBP, FileFormat.TIFF, FileFormat.BMP]
)
def test_resize_formats(images, tmp_path, format):
    (path,) = run(ImageConverter(format), images[0], tmp_path, {"width": 60})
    with Image.open(path) as image:
        assert image.size == (60, 120)


def test_heif_image_can_be_converted_to_png(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    if not pillow_heif.libheif_info().get("HEIF"):
        pytest.skip("HEIF encoder unavailable")
    pillow_heif.register_heif_opener()
    source = tmp_path / "sample.heic"
    Image.new("RGB", (24, 12), "red").save(source, format="HEIF")

    (output,) = run(ImageConverter(FileFormat.PNG), source, tmp_path)
    with Image.open(output) as image:
        assert image.size == (24, 12)
        red, green, blue = image.convert("RGB").getpixel((12, 6))
        assert red > 200 and green < 40 and blue < 40


def test_target_size(images, tmp_path):
    (path,) = run(
        ImageConverter(FileFormat.JPEG),
        images[0],
        tmp_path,
        {"target_kib": 1, "allow_downscale": True},
    )
    assert path.stat().st_size <= 1024


def test_png_target_with_explicit_downscaling(tmp_path):
    source = tmp_path / "noise.png"
    Image.effect_noise((100, 100), 100).save(source)
    # A 1 KiB target is achievable after resizing; ensure it is actually enforced.
    (path,) = run(
        ImageConverter(FileFormat.PNG),
        source,
        tmp_path,
        {"target_kib": 1, "allow_downscale": True},
    )
    assert path.stat().st_size <= 1024


def test_image_cancellation(images, tmp_path):
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConversionCancelled):
        run(ImagesPdfConverter(), images, tmp_path, token=token)
    assert not list(tmp_path.glob("*.pdf"))


def test_animation_rejected(tmp_path):
    path = tmp_path / "animated.gif"
    Image.new("RGB", (10, 10), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")]
    )
    with pytest.raises(ConversionError, match="Multi-frame"):
        run(ImageConverter(FileFormat.PNG), path, tmp_path)


def test_lossless_pdf_preserves_text(fixture_dir, tmp_path):
    (path,) = run(PdfCompressConverter(), fixture_dir / "one_page.pdf", tmp_path)
    with pymupdf.open(path) as doc:
        assert "Local PDF Toolkit fixture" in doc[0].get_text()


def test_pdf_size_target_and_rasterization(fixture_dir, tmp_path):
    (path,) = run(
        PdfCompressConverter(),
        fixture_dir / "one_page.pdf",
        tmp_path,
        {"mode": "rasterized", "target_kib": 50, "dpi": 72},
    )
    assert path.stat().st_size <= 50 * 1024
    with pymupdf.open(path) as doc:
        assert not doc[0].get_text()
        assert len(doc[0].get_images()) == 1


def test_pdf_impossible_target_no_partial_output(fixture_dir, tmp_path):
    with pytest.raises(ConversionError, match="Target size"):
        run(
            PdfCompressConverter(),
            fixture_dir / "one_page.pdf",
            tmp_path,
            {"mode": "rasterized", "target_kib": 1},
        )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("format", [FileFormat.PNG, FileFormat.WEBP, FileFormat.BMP])
def test_cmyk_jpeg_converts_to_other_image_formats(tmp_path, format):
    source = tmp_path / "print.jpg"
    Image.new("CMYK", (20, 10), (0, 255, 255, 0)).save(source)
    (path,) = run(ImageConverter(format), source, tmp_path)
    with Image.open(path) as image:
        assert image.size == (20, 10)
        red, green, blue = image.convert("RGB").getpixel((5, 5))
        assert red > 240 and green < 20 and blue < 20


def test_precancelled_image_does_not_decode_input(tmp_path, monkeypatch):
    from local_pdf_toolkit.converters import images as module

    def unexpected_decode(path):
        pytest.fail("A cancelled job must not decode an image")

    monkeypatch.setattr(module, "open_image", unexpected_decode)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConversionCancelled):
        run(ImageConverter(FileFormat.PNG), tmp_path / "unused.png", tmp_path, token=token)


def test_transparent_palette_preserved_in_png_and_white_in_bmp(tmp_path):
    source = tmp_path / "palette.png"
    image = Image.new("P", (10, 10), 0)
    image.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    image.save(source, transparency=0)
    (png,) = run(ImageConverter(FileFormat.PNG), source, tmp_path)
    (bmp,) = run(ImageConverter(FileFormat.BMP), source, tmp_path)
    with Image.open(png) as exported:
        assert exported.convert("RGBA").getpixel((0, 0))[3] == 0
    with Image.open(bmp) as exported:
        assert exported.convert("RGB").getpixel((0, 0)) == (255, 255, 255)


def test_single_string_image_path_is_one_pdf_input(images, tmp_path):
    (output,) = run(ImagesPdfConverter(), str(images[0]), tmp_path)
    with pymupdf.open(output) as document:
        assert len(document) == 1


def test_cmyk_tiff_to_png(tmp_path):
    source = tmp_path / "print.tiff"
    Image.new("CMYK", (20, 10), (0, 255, 255, 0)).save(source)
    (output,) = run(ImageConverter(FileFormat.PNG), source, tmp_path)
    with Image.open(output) as image:
        assert image.mode == "RGB"
        assert image.getpixel((5, 5)) == (255, 0, 0)


def test_png_metadata_removed_without_losing_alpha(tmp_path):
    from PIL.PngImagePlugin import PngInfo

    source = tmp_path / "metadata.png"
    metadata = PngInfo()
    metadata.add_text("Author", "Private author")
    exif = Image.Exif()
    exif[315] = "Private author"
    Image.new("RGBA", (10, 10), (255, 0, 0, 80)).save(
        source, pnginfo=metadata, exif=exif, icc_profile=b"private profile"
    )
    (output,) = run(ImageConverter(FileFormat.PNG), source, tmp_path)
    with Image.open(output) as image:
        assert image.getpixel((0, 0)) == (255, 0, 0, 80)
        assert "Author" not in image.info
        assert "icc_profile" not in image.info
        assert not image.getexif()
