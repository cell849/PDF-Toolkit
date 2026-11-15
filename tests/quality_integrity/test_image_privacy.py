"""An external metadata reader checks the converters' metadata-removal promise."""

import pytest
from PIL import Image, PngImagePlugin, TiffImagePlugin

from local_pdf_toolkit.converters.images import ImageConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.formats import FileFormat

from .independent_pdf import poppler, sha256


@pytest.mark.parametrize("source_kind", ["JPEG", "PNG", "TIFF"])
@pytest.mark.parametrize(
    "output_kind",
    [FileFormat.JPEG, FileFormat.PNG, FileFormat.TIFF, FileFormat.BMP, FileFormat.WEBP],
)
def test_converted_image_removes_personal_metadata_in_external_reader(
    tmp_path, source_kind, output_kind
):
    source = tmp_path / ("source." + source_kind.lower())
    metadata = Image.Exif()
    metadata[315] = "SECRET-OWNER"
    metadata[306] = "2024:03:04 05:06:07"
    kwargs = {"exif": metadata}
    if source_kind == "PNG":
        text = PngImagePlugin.PngInfo()
        text.add_text("Author", "SECRET-PNG-AUTHOR")
        text.add_itxt("XML:com.adobe.xmp", "SECRET-XMP")
        kwargs["pnginfo"] = text
    elif source_kind == "TIFF":
        tags = TiffImagePlugin.ImageFileDirectory_v2()
        tags[270] = "SECRET-DESCRIPTION"
        tags[315] = "SECRET-TIFF-AUTHOR"
        kwargs["tiffinfo"] = tags
    with Image.new("RGB", (24, 12), (245, 15, 5)) as image:
        image.save(source, format=source_kind, **kwargs)
    before = sha256(source)
    assert b"SECRET" in poppler("exiftool", "-j", "-a", "-u", source)
    (result,) = ImageConverter(output_kind).convert(
        source, tmp_path, {}, lambda _: None, CancellationToken()
    )
    assert b"SECRET" not in poppler("exiftool", "-j", "-a", "-u", result)
    with Image.open(result) as image:
        assert image.size == (24, 12)
        r, g, b = image.convert("RGB").getpixel((12, 6))
        assert r >= 230 and g < 30 and b < 30
    assert sha256(source) == before
