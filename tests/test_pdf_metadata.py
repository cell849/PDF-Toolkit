import json

import pymupdf
import pytest

from local_pdf_toolkit.converters.pdf_metadata import PdfMetadataConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError


@pytest.fixture
def private_pdf(tmp_path):
    path = tmp_path / "PrivateOwnerCanary.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=144, height=144)
        page.insert_text((10, 30), "Visible content")
        page.insert_text((10, 50), "Private hidden text", render_mode=3)
        document.set_metadata({"author": "PrivateOwnerCanary", "title": "Private title"})
        document.set_xml_metadata("<xmp>PrivateOwnerCanary</xmp>")
        document.embfile_add("secret.txt", b"Private attachment")
        annotation = page.add_text_annot((80, 80), "Private comment")
        annotation.set_info(title="Private author")
        document.save(path)
    return path


def test_rebuild_drops_original_objects_preserves_page_appearance(private_pdf, tmp_path):
    before = private_pdf.read_bytes()
    result, report = PdfMetadataConverter().convert(
        private_pdf, tmp_path, {"dpi": 72}, lambda _: None, CancellationToken()
    )
    assert before == private_pdf.read_bytes()
    assert "Private" not in result.name
    with pymupdf.open(private_pdf) as original, pymupdf.open(result) as clean:
        assert len(clean) == 1
        assert not clean.get_xml_metadata()
        assert clean.embfile_count() == 0
        assert not clean.metadata.get("author")
        assert clean.xref_get_key(-1, "ID")[0] == "null"
        assert not clean[0].get_text()
        assert not list(clean[0].annots() or ())
        assert clean[0].rect == original[0].rect
        assert clean[0].get_pixmap(dpi=72).samples == original[0].get_pixmap(dpi=72).samples
    assert json.loads(report.read_text())["pages"] == 1
    assert "Private" not in report.read_text()


def test_pdf_cancel_discards_all_outputs(private_pdf, tmp_path):
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        PdfMetadataConverter().convert(private_pdf, tmp_path, {}, lambda _: token.cancel(), token)
    assert list(tmp_path.iterdir()) == [private_pdf]


def test_invalid_options_rejected():
    with pytest.raises(ConversionError):
        PdfMetadataConverter().validate_options({"dpi": True})
