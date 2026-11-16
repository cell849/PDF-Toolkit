import pytest
from PIL import Image

from local_pdf_toolkit.converters.image_comparison import ImageComparisonConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled


def test_candidates_preserve_dimensions_and_source_and_drop_metadata(tmp_path):
    source = tmp_path / "input.png"
    with Image.new("RGBA", (120, 80), (255, 0, 0, 0)) as image:
        image.save(source)
    original = source.read_bytes()
    converter = ImageComparisonConverter()
    outputs = converter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    assert {p.suffix for p in outputs} == {".jpg", ".png", ".webp"}
    assert source.read_bytes() == original
    for path in outputs:
        with Image.open(path) as image:
            assert image.size == (120, 80)
            assert not image.getexif()
            if path.suffix == ".jpg":
                assert image.convert("RGB").getpixel((0, 0)) == (255, 255, 255)
            else:
                assert image.convert("RGBA").getpixel((0, 0))[3] == 0
    prior = {p: p.read_bytes() for p in outputs}
    with pytest.raises(FileExistsError):
        converter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    assert all(p.read_bytes() == data for p, data in prior.items())


def test_cancel_between_formats_publishes_nothing(tmp_path):
    source = tmp_path / "input.png"
    with Image.new("RGB", (10, 10)) as image:
        image.save(source)
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        ImageComparisonConverter().convert(source, tmp_path, {}, lambda _: token.cancel(), token)
    assert list(tmp_path.iterdir()) == [source]
