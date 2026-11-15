"""Resource guard regressions; dangerous page rasters are intercepted before allocation."""

import math

import pymupdf
import pytest

from local_pdf_toolkit.converters.compress import PdfCompressConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode

from .independent_pdf import sha256, write_pdf


@pytest.mark.parametrize("width,height", [(20_000_000, 1), (10_000_000, 2)])
def test_raster_compression_bounds_rounded_dimensions(tmp_path, monkeypatch, width, height):
    source = write_pdf(tmp_path / "narrow.pdf", pages=1, width=width, height=height)
    before = sha256(source)
    output = tmp_path / "out"
    output.mkdir()

    def intercept_render(page, *, dpi, **kwargs):
        pixels = math.ceil(page.rect.width * dpi / 72) * math.ceil(page.rect.height * dpi / 72)
        assert pixels <= 40_000_000, f"Unsafe allocation requested: {pixels:,} pixels at {dpi} DPI"
        # A safe request is sufficient; do not allocate even a permitted large raster.
        raise ConversionError(ErrorCode.INVALID_INPUT, "Safe allocation intercepted by test")

    monkeypatch.setattr(pymupdf.Page, "get_pixmap", intercept_render)
    with pytest.raises(ConversionError):
        PdfCompressConverter().convert(
            source,
            output,
            {"mode": "rasterized", "dpi": 300},
            lambda _: None,
            CancellationToken(),
        )
    assert sha256(source) == before
    assert list(output.iterdir()) == []
