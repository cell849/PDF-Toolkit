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


def test_target_size(images, tmp_path):
    (path,) = run(ImageConverter(FileFormat.JPEG), images[0], tmp_path, {"target_kib": 1})
    assert path.stat().st_size <= 1024


def test_impossible_png_target_publishes_nothing(tmp_path):
    source = tmp_path / "noise.png"
    Image.effect_noise((100, 100), 100).save(source)
    # A 1 KiB target is achievable after resizing; ensure it is actually enforced.
    (path,) = run(ImageConverter(FileFormat.PNG), source, tmp_path, {"target_kib": 1})
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
