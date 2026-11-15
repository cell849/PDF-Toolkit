import hashlib
import json
import os
from types import SimpleNamespace

import pymupdf
import pytest

from local_pdf_toolkit.converters import redaction as redaction_module
from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.converters.redaction import (
    MASK_PADDING_PIXELS,
    PdfRedactionConverter,
    redaction_converters,
)
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


def marks(page=1, **bounds):
    return json.dumps([{"page": page, "x0": 0.05, "y0": 0.05, "x1": 0.8, "y1": 0.3, **bounds}])


def convert(
    source, output, regions=None, *, dpi=72, progress=lambda _: None, token=None, source_sha256=""
):
    return PdfRedactionConverter().convert(
        source,
        output,
        {
            "dpi": dpi,
            "regions": marks() if regions is None else regions,
            "source_sha256": source_sha256,
        },
        progress,
        token or CancellationToken(),
    )


@pytest.fixture
def private_pdf(tmp_path):
    path = tmp_path / "PrivateOwnerCanary.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=240, height=300)
        page.insert_text((20, 40), "TOP SECRET", fontsize=16)
        page.insert_text((20, 150), "Visible content stays")
        page.insert_text((20, 180), "HiddenPrivateCanary", render_mode=3)
        annotation = page.add_text_annot((180, 200), "Private comment")
        annotation.set_info(title="Private author")
        page.insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(20, 140, 150, 160),
                "uri": "https://private.invalid/",
            }
        )
        widget = pymupdf.Widget()
        widget.field_name = "PrivateFieldCanary"
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.field_value = "Visible field"
        widget.rect = pymupdf.Rect(20, 220, 180, 245)
        page.add_widget(widget)
        document.new_page(width=180, height=144).insert_text((20, 40), "Unmarked page stays")
        document.set_metadata({"author": "PrivateOwnerCanary", "title": "Private title"})
        document.set_xml_metadata("<xmp>PrivateOwnerCanary</xmp>")
        document.embfile_add("secret.txt", b"PrivateAttachmentCanary")
        script = document.get_new_xref()
        document.update_object(script, "<< /S /JavaScript /JS (PrivateScriptCanary) >>")
        document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{script} 0 R")
        document.save(path)
    return path


def test_factory_and_defaults():
    (converter,) = redaction_converters()
    assert isinstance(converter, PdfRedactionConverter)
    assert converter.spec.operation_id == "pdf.redact"
    assert converter.spec.input_formats == converter.spec.output_formats == (FileFormat.PDF,)
    assert converter.validate_options({"regions": marks()})["dpi"] == 150
    assert converter.validate_options({"regions": marks()})["source_sha256"] == ""


@pytest.mark.parametrize("digest", [None, False, 123, "a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_invalid_source_digest(digest):
    with pytest.raises(ConversionError) as error:
        PdfRedactionConverter().validate_options({"regions": marks(), "source_sha256": digest})
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_same_size_and_timestamp_source_change_is_rejected_before_parser_open(
    private_pdf, tmp_path, monkeypatch
):
    before = private_pdf.read_bytes()
    source_stat = private_pdf.stat()
    digest = hashlib.sha256(before).hexdigest()
    changed = before.replace(b"PrivateOwnerCanary", b"ChangedOwnerCanary")
    assert changed != before and len(changed) == len(before)
    private_pdf.write_bytes(changed)
    os.utime(private_pdf, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
    assert private_pdf.stat().st_mtime_ns == source_stat.st_mtime_ns

    def parser_must_not_open(*_):
        pytest.fail("A source with a different digest must be rejected before PDF parsing.")

    monkeypatch.setattr(PdfImagesConverter, "_open", parser_must_not_open)
    with pytest.raises(ConversionError) as error:
        convert(private_pdf, tmp_path, source_sha256=digest)
    assert error.value.code == ErrorCode.INVALID_INPUT
    assert list(tmp_path.iterdir()) == [private_pdf]
    assert private_pdf.read_bytes() == changed


def test_verified_snapshot_is_rendered_if_original_changes_after_copy(
    private_pdf, tmp_path, monkeypatch
):
    before = private_pdf.read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    with pymupdf.open(private_pdf) as original:
        expected_unmarked_page = original[1].get_pixmap(dpi=72).samples
    open_pdf = PdfImagesConverter._open
    snapshots = []

    def open_snapshot(converter, path):
        assert path != private_pdf
        assert path.read_bytes() == before
        snapshots.append(path)
        # Replacing the original after verification must not affect rendered bytes.
        private_pdf.write_bytes(b"changed after verified snapshot")
        return open_pdf(converter, path)

    monkeypatch.setattr(PdfImagesConverter, "_open", open_snapshot)
    result, report = convert(private_pdf, tmp_path, source_sha256=digest)
    with pymupdf.open(result) as redacted:
        assert redacted[1].get_pixmap(dpi=72).samples == expected_unmarked_page
    assert snapshots and all(not path.exists() for path in snapshots)
    assert digest not in report.read_text()


def test_snapshot_leaves_source_untouched_and_cleans_temporary_copy(
    private_pdf, tmp_path, monkeypatch
):
    before = private_pdf.read_bytes()
    open_pdf = PdfImagesConverter._open
    snapshots = []

    def open_snapshot(converter, path):
        assert path != private_pdf
        snapshots.append(path)
        return open_pdf(converter, path)

    monkeypatch.setattr(PdfImagesConverter, "_open", open_snapshot)
    convert(private_pdf, tmp_path, source_sha256=hashlib.sha256(before).hexdigest())
    assert private_pdf.read_bytes() == before
    assert snapshots and all(not path.exists() for path in snapshots)


@pytest.mark.parametrize("reported_size", [0, None])
def test_snapshot_limit_covers_initial_size_and_stream_growth(
    private_pdf, tmp_path, monkeypatch, reported_size
):
    monkeypatch.setattr(redaction_module, "MAX_INPUT_BYTES", 64)
    monkeypatch.setattr(redaction_module, "SNAPSHOT_CHUNK_BYTES", 32)
    if reported_size is not None:
        source_stat = private_pdf.stat()
        fstat = os.fstat

        def initial_source_stat(descriptor):
            actual = fstat(descriptor)
            if actual.st_ino == source_stat.st_ino:
                return SimpleNamespace(st_mode=actual.st_mode, st_size=reported_size)
            return actual

        monkeypatch.setattr(redaction_module.os, "fstat", initial_source_stat)
    with pytest.raises(ConversionError) as error:
        convert(private_pdf, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT
    assert list(tmp_path.iterdir()) == [private_pdf]


def test_cancellation_during_snapshot_discards_copy(private_pdf, tmp_path, monkeypatch):
    temporary_directory = redaction_module.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        redaction_module.tempfile,
        "TemporaryDirectory",
        lambda **kwargs: temporary_directory(dir=tmp_path, **kwargs),
    )
    monkeypatch.setattr(redaction_module, "SNAPSHOT_CHUNK_BYTES", 32)

    class CancelDuringCopy(CancellationToken):
        checks = 0

        def raise_if_cancelled(self):
            self.checks += 1
            if self.checks == 3:
                self.cancel()
            super().raise_if_cancelled()

    with pytest.raises(ConversionCancelled):
        convert(private_pdf, tmp_path, token=CancelDuringCopy())
    assert list(tmp_path.iterdir()) == [private_pdf]


@pytest.mark.parametrize("dpi", [72, 150, 300])
def test_multiple_marks_on_multiple_pages_and_edge_padding(private_pdf, tmp_path, dpi):
    regions = json.dumps(
        [
            {"page": 1, "x0": 0, "y0": 0, "x1": 0.01, "y1": 0.01},
            {"page": 1, "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.2},
            {"page": 2, "x0": 0.9, "y0": 0.9, "x1": 1, "y1": 1},
        ]
    )
    result, report = convert(private_pdf, tmp_path, regions, dpi=dpi)
    with pymupdf.open(result) as document:
        first = document[0].get_pixmap(dpi=dpi, alpha=False)
        second = document[1].get_pixmap(dpi=dpi, alpha=False)
        assert first.pixel(0, 0) == (0, 0, 0)
        assert first.pixel(int(first.width * 0.3), int(first.height * 0.15)) == (0, 0, 0)
        assert second.pixel(second.width - 1, second.height - 1) == (0, 0, 0)
        assert all(not page.get_text() for page in document)
    assert json.loads(report.read_text())["masked_regions"] == 3


def test_output_names_are_neutral_and_unique(private_pdf, tmp_path):
    first = convert(private_pdf, tmp_path)
    second = convert(private_pdf, tmp_path)
    assert len(set(first + second)) == 4
    assert all("Private" not in path.name for path in first + second)


def test_mask_removes_text_and_hidden_objects_preserves_original_and_other_pixels(
    private_pdf, tmp_path
):
    digest = hashlib.sha256(private_pdf.read_bytes()).digest()
    updates = []
    result, report_path = convert(private_pdf, tmp_path, progress=updates.append)
    assert hashlib.sha256(private_pdf.read_bytes()).digest() == digest
    assert "Private" not in result.name
    with pymupdf.open(private_pdf) as source, pymupdf.open(result) as result_pdf:
        assert len(result_pdf) == 2
        assert not result_pdf.embfile_count()
        assert not result_pdf.get_xml_metadata()
        assert result_pdf.xref_get_key(-1, "Info")[0] == "null"
        assert result_pdf.xref_get_key(-1, "ID")[0] == "null"
        assert result_pdf.xref_get_key(result_pdf.pdf_catalog(), "OpenAction")[0] == "null"
        for page in result_pdf:
            assert not page.get_text()
            assert not list(page.annots())
            assert not list(page.widgets())
            assert not page.get_links()
        assert result_pdf[0].rect == source[0].rect
        original_pixels = source[0].get_pixmap(dpi=72, alpha=False)
        result_pixels = result_pdf[0].get_pixmap(dpi=72, alpha=False)
        assert any(value != 255 for value in original_pixels.samples)
        # The original visible text at this point is replaced by solid black.
        assert result_pixels.pixel(30, 35) == (0, 0, 0)
        # Entire rows far below the mask, including visible annotations/forms, survive.
        offset = 100 * result_pixels.stride
        assert result_pixels.samples[offset:] == original_pixels.samples[offset:]
        assert result_pdf[1].get_pixmap(dpi=72).samples == source[1].get_pixmap(dpi=72).samples
        objects = "\n".join(
            result_pdf.xref_object(xref) for xref in range(1, result_pdf.xref_length())
        )
        assert "Private" not in objects
        assert "/JavaScript" not in objects
    report = json.loads(report_path.read_text())
    assert report["masked_regions"] == report["marked_pages"] == 1
    assert report["pages"] == 2
    assert "Originals are untouched" in report["policy"]
    assert "outside the marked areas" in report["limits"]
    assert "Private" not in report_path.read_text()
    assert "x0" not in report_path.read_text()
    assert updates[-1].completed == updates[-1].total == 2


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_normalized_marks_use_displayed_rotation_and_crop(tmp_path, rotation):
    source_path = tmp_path / "cropped.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.draw_rect(page.rect, color=None, fill=(0.2, 0.4, 0.6))
        page.draw_rect(pymupdf.Rect(60, 90, 100, 150), color=None, fill=(1, 0, 0))
        page.set_cropbox(pymupdf.Rect(40, 60, 260, 340))
        page.set_rotation(rotation)
        document.save(source_path)
    region = {"x0": 0.1, "y0": 0.2, "x1": 0.4, "y1": 0.5}
    result, _ = convert(source_path, tmp_path, marks(**region))
    with pymupdf.open(source_path) as source, pymupdf.open(result) as redacted:
        assert redacted[0].rect == source[0].rect
        assert redacted[0].rotation == 0
        expected = source[0].get_pixmap(dpi=72, colorspace=pymupdf.csRGB, alpha=False)
        expected.set_rect(
            pymupdf.IRect(
                int(expected.width * 0.1) - MASK_PADDING_PIXELS,
                int(expected.height * 0.2) - MASK_PADDING_PIXELS,
                int(expected.width * 0.4) + MASK_PADDING_PIXELS,
                int(expected.height * 0.5) + MASK_PADDING_PIXELS,
            ),
            (0, 0, 0),
        )
        actual = redacted[0].get_pixmap(dpi=72, colorspace=pymupdf.csRGB, alpha=False)
        assert actual.samples == expected.samples


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"regions": "[]"},
        {"regions": "null"},
        {"regions": "{}"},
        {"regions": "not json"},
        {"regions": []},
        {"regions": "[" * 2000},
        {"regions": " " * (128 * 1024 + 1)},
        {"regions": json.dumps([{}] * 1001)},
        {"regions": marks(page=0)},
        {"regions": marks(page=True)},
        {"regions": marks(page=1.0)},
        {"regions": marks(x0=-0.1)},
        {"regions": marks(x1=1.1)},
        {"regions": marks(x0=0.8)},
        {"regions": marks(y1=0.05)},
        {"regions": marks(x0=True)},
        {"regions": marks(x0=float("nan"))},
        {"regions": marks(x1=float("inf"))},
        {"regions": marks(x1="0.5")},
        {"regions": marks(extra="unrecognized")},
        {"regions": marks(), "dpi": True},
        {"regions": marks(), "dpi": 96},
        {"regions": marks(), "unknown": True},
    ],
)
def test_invalid_options(options):
    with pytest.raises(ConversionError) as error:
        PdfRedactionConverter().validate_options(options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_out_of_range_page_and_large_page_publish_nothing(private_pdf, tmp_path):
    with pytest.raises(ConversionError) as error:
        convert(private_pdf, tmp_path, marks(page=3))
    assert error.value.code == ErrorCode.INVALID_OPTIONS
    assert list(tmp_path.iterdir()) == [private_pdf]
    large = tmp_path / "large.pdf"
    with pymupdf.open() as document:
        document.new_page(width=10000, height=10000)
        document.save(large)
    with pytest.raises(ConversionError) as error:
        convert(large, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT
    assert set(tmp_path.iterdir()) == {private_pdf, large}


@pytest.mark.parametrize("completed", [0, 1, 2])
def test_cancellation_discards_all_outputs(private_pdf, tmp_path, completed):
    token = CancellationToken()

    def progress(update):
        if update.completed == completed:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        convert(private_pdf, tmp_path, progress=progress, token=token)
    assert list(tmp_path.iterdir()) == [private_pdf]


def test_strict_pdf_input_validation(tmp_path):
    converter = PdfRedactionConverter()
    invalid = tmp_path / "fake.pdf"
    invalid.write_bytes(b"not PDF")
    with pytest.raises(ConversionError) as error:
        convert(invalid, tmp_path)
    assert error.value.code == ErrorCode.INVALID_INPUT
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    with pytest.raises(ConversionError) as error:
        converter.validate_input(encrypted)
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED


def test_verification_failure_discards_outputs(private_pdf, tmp_path, monkeypatch):
    save = pymupdf.Document.save

    def unsafe_save(document, *args, **kwargs):
        document[0].insert_text((10, 100), "Unexpected selectable text")
        return save(document, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Document, "save", unsafe_save)
    with pytest.raises(ConversionError) as error:
        convert(private_pdf, tmp_path)
    assert error.value.code == ErrorCode.CONVERSION_FAILED
    assert list(tmp_path.iterdir()) == [private_pdf]
