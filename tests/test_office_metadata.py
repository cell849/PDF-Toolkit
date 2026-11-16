import io
import json
import zipfile
from copy import copy

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
from lxml import etree
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from PIL import Image

from local_pdf_toolkit.converters.odf_metadata import (
    MANIFEST,
    MIMES,
    OFFICE,
    TABLE,
    TEXT,
    OdfMetadataConverter,
)
from local_pdf_toolkit.converters.office_metadata import OfficeMetadataConverter, W
from local_pdf_toolkit.converters.text_metadata import TextMetadataConverter, clean_rtf
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError
from local_pdf_toolkit.core.formats import FileFormat

PRIVATE = "PrivateAuthorCanary98362"


def run(converter, path, out, token=None, progress=lambda _: None):
    return converter.convert(path, out, {}, progress, token or CancellationToken())


def change_zip(path, callback):
    with zipfile.ZipFile(path) as package:
        parts = {n: package.read(n) for n in package.namelist()}
    callback(parts)
    with zipfile.ZipFile(path, "w") as package:
        package.comment = PRIVATE.encode()
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, (2025, 1, 2, 12, 0, 0))
            info.comment = PRIVATE.encode()
            package.writestr(info, data)


def check_output(path, report):
    assert PRIVATE not in path.name
    assert PRIVATE not in report.read_text()
    with zipfile.ZipFile(path) as package:
        assert not package.comment
        for info in package.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert not info.comment and not info.extra
            assert PRIVATE.encode() not in package.read(info)


@pytest.fixture
def word(tmp_path):
    path = tmp_path / "private.docx"
    doc = Document()
    doc.core_properties.author = PRIVATE
    doc.core_properties.last_modified_by = PRIVATE
    p = doc.add_paragraph()
    p.add_run("Visible").bold = True
    ins = OxmlElement("w:ins")
    ins.set(qn("w:author"), PRIVATE)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = " accepted"
    r.append(t)
    ins.append(r)
    p._p.append(ins)
    deleted = OxmlElement("w:del")
    deleted.set(qn("w:author"), PRIVATE)
    r = OxmlElement("w:r")
    t = OxmlElement("w:delText")
    t.text = PRIVATE
    r.append(t)
    deleted.append(r)
    p._p.append(deleted)
    doc.sections[0].header.paragraphs[0].text = "Public header"
    stream = io.BytesIO()
    image = Image.new("RGB", (10, 10), "red")
    exif = Image.Exif()
    exif[315] = PRIVATE
    image.save(stream, format="JPEG", exif=exif)
    stream.seek(0)
    doc.add_picture(stream, width=Inches(1))
    doc.save(path)
    change_zip(path, lambda _: None)
    return path


@pytest.fixture
def excel(tmp_path):
    path = tmp_path / "private.xlsx"
    book = Workbook()
    book.properties.creator = PRIVATE
    sheet = book.active
    sheet["A1"] = "Visible"
    sheet["B1"] = "=SUM(1,2)"
    sheet["A1"].comment = Comment("Private comment", PRIVATE)
    font = copy(sheet["A1"].font)
    font.bold = True
    sheet["A1"].font = font
    book.save(path)
    book.close()
    change_zip(path, lambda _: None)
    return path


def test_word_properties_revisions_and_images_removed_without_losing_style(word, tmp_path):
    original = word.read_bytes()
    output, report = run(OfficeMetadataConverter(FileFormat.DOCX), word, tmp_path)
    assert word.read_bytes() == original
    doc = Document(output)
    assert doc.paragraphs[0].text == "Visible accepted"
    assert doc.paragraphs[0].runs[0].bold
    assert doc.sections[0].header.paragraphs[0].text == "Public header"
    assert len(doc.inline_shapes) == 1 and doc.inline_shapes[0].width == Inches(1)
    check_output(output, report)
    with zipfile.ZipFile(output) as package:
        assert not any(n.startswith(("docProps/", "customXml/")) for n in package.namelist())
        media = next(n for n in package.namelist() if "/media/" in n)
        with Image.open(io.BytesIO(package.read(media))) as image:
            assert not image.getexif()


def test_excel_metadata_comments_removed_formulas_and_styles_preserved(excel, tmp_path):
    original = excel.read_bytes()
    output, report = run(OfficeMetadataConverter(FileFormat.XLSX), excel, tmp_path)
    book = load_workbook(output)
    sheet = book.active
    assert sheet["A1"].value == "Visible" and sheet["A1"].font.bold
    assert sheet["B1"].value == "=SUM(1,2)" and sheet["A1"].comment is None
    book.close()
    assert excel.read_bytes() == original
    check_output(output, report)


@pytest.mark.parametrize(
    "part",
    [
        "word/embeddings/a.bin",
        "word/vbaProject.bin",
        "word/charts/chart1.xml",
        "_xmlsignatures/sig1.xml",
    ],
)
def test_unsupported_word_parts_fail_without_output(word, tmp_path, part):
    change_zip(word, lambda parts: parts.update({part: b"unknown"}))
    with pytest.raises(ConversionError):
        run(OfficeMetadataConverter(FileFormat.DOCX), word, tmp_path)
    assert list(tmp_path.iterdir()) == [word]


def test_hidden_excel_sheet_rejected(excel, tmp_path):
    book = load_workbook(excel)
    book.create_sheet("private").sheet_state = "hidden"
    book.save(excel)
    book.close()
    with pytest.raises(ConversionError, match="Hidden"):
        run(OfficeMetadataConverter(FileFormat.XLSX), excel, tmp_path)


def test_word_table_revisions_rejected(word, tmp_path):
    def inject(parts):
        tree = etree.fromstring(parts["word/document.xml"])
        row = etree.SubElement(tree.find("{" + W + "}body"), "{" + W + "}tr")
        props = etree.SubElement(row, "{" + W + "}trPr")
        etree.SubElement(props, "{" + W + "}del")
        parts["word/document.xml"] = etree.tostring(tree)

    change_zip(word, inject)
    with pytest.raises(ConversionError, match="table-structure"):
        run(OfficeMetadataConverter(FileFormat.DOCX), word, tmp_path)


@pytest.mark.parametrize("element", ["documentProtection", "writeProtection"])
def test_word_protection_credentials_are_never_published(word, tmp_path, element):
    def inject(parts):
        root = etree.fromstring(parts["word/settings.xml"])
        protection = etree.SubElement(root, "{" + W + "}" + element)
        protection.set("{" + W + "}hash", "UHJpdmF0ZVBhc3N3b3JkSGFzaA==")
        protection.set("{" + W + "}salt", "UHJpdmF0ZVNhbHQ=")
        if element == "documentProtection":
            protection.set("{" + W + "}edit", "readOnly")
            protection.set("{" + W + "}enforcement", "1")
        parts["word/settings.xml"] = etree.tostring(root)

    change_zip(word, inject)
    original = word.read_bytes()
    with pytest.raises(ConversionError, match="Protected Word"):
        run(OfficeMetadataConverter(FileFormat.DOCX), word, tmp_path)
    assert word.read_bytes() == original
    assert list(tmp_path.iterdir()) == [word]


def test_word_text_hidden_in_web_view_is_rejected(word, tmp_path):
    def inject(parts):
        root = etree.fromstring(parts["word/document.xml"])
        properties = root.find(".//{" + W + "}rPr")
        etree.SubElement(properties, "{" + W + "}webHidden")
        parts["word/document.xml"] = etree.tostring(root)

    change_zip(word, inject)
    with pytest.raises(ConversionError, match="Hidden Word"):
        run(OfficeMetadataConverter(FileFormat.DOCX), word, tmp_path)
    assert list(tmp_path.iterdir()) == [word]


def test_office_cancel_keeps_source(word, tmp_path):
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        run(
            OfficeMetadataConverter(FileFormat.DOCX),
            word,
            tmp_path,
            token,
            lambda _: token.cancel(),
        )
    assert list(tmp_path.iterdir()) == [word]


def make_odf(path, kind):
    office = OFFICE
    text = TEXT
    table = TABLE
    content = etree.Element(
        "{" + office + "}document-content", nsmap={"office": office, "text": text, "table": table}
    )
    body = etree.SubElement(content, "{" + office + "}body")
    section = etree.SubElement(
        body,
        "{"
        + office
        + "}"
        + {FileFormat.ODT: "text", FileFormat.ODS: "spreadsheet", FileFormat.ODP: "presentation"}[
            kind
        ],
    )
    if kind == FileFormat.ODS:
        tab = etree.SubElement(section, "{" + table + "}table")
        tab.set("{" + table + "}name", "Public sheet")
        row = etree.SubElement(tab, "{" + table + "}table-row")
        cell = etree.SubElement(row, "{" + table + "}table-cell")
        cell.set("{" + office + "}value-type", "string")
        etree.SubElement(cell, "{" + text + "}p").text = "Visible"
    elif kind == FileFormat.ODP:
        draw = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
        page = etree.SubElement(section, "{" + draw + "}page")
        page.set("{" + draw + "}name", "Public slide")
        box = etree.SubElement(page, "{" + draw + "}frame")
        text_box = etree.SubElement(box, "{" + draw + "}text-box")
        etree.SubElement(text_box, "{" + text + "}p").text = "Visible"
    else:
        etree.SubElement(section, "{" + text + "}p").text = "Visible"
    meta = etree.SubElement(section, "{" + office + "}annotation")
    etree.SubElement(meta, "{" + text + "}p").text = PRIVATE
    manifest = etree.Element("{" + MANIFEST + "}manifest")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", MIMES[kind])
        archive.writestr("content.xml", etree.tostring(content))
        archive.writestr("META-INF/manifest.xml", etree.tostring(manifest))
        archive.writestr("meta.xml", f"<meta>{PRIVATE}</meta>")
        archive.writestr("settings.xml", f"<settings>{PRIVATE}</settings>")


@pytest.mark.parametrize("kind", [FileFormat.ODT, FileFormat.ODS, FileFormat.ODP])
def test_odf_properties_comments_zip_cleaned_and_text_preserved(tmp_path, kind):
    path = tmp_path / ("source." + kind.value)
    make_odf(path, kind)
    before = path.read_bytes()
    output, report = run(OdfMetadataConverter(), path, tmp_path)
    assert path.read_bytes() == before
    check_output(output, report)
    with zipfile.ZipFile(output) as archive:
        assert archive.infolist()[0].filename == "mimetype"
        assert archive.infolist()[0].compress_type == zipfile.ZIP_STORED
        assert "meta.xml" not in archive.namelist() and "settings.xml" not in archive.namelist()
        assert b"Visible" in archive.read("content.xml")


def test_odf_unsupported_objects_fail(tmp_path):
    path = tmp_path / "source.odt"
    make_odf(path, FileFormat.ODT)
    change_zip(path, lambda parts: parts.update({"Object1/content.xml": b"<secret/>"}))
    with pytest.raises(ConversionError, match="Unsupported OpenDocument"):
        run(OdfMetadataConverter(), path, tmp_path)


def test_rtf_properties_and_nested_escapes_removed_formatting_preserved(tmp_path):
    source = tmp_path / "source.rtf"
    data = (
        r"{\rtf1\ansi{\fonttbl{\f0 Arial;}}{\info{\author "
        + PRIVATE
        + r"}{\title secret\{data\}}}{\*\generator "
        + PRIVATE
        + r";}\b Visible\b0\par escaped \{brace\}}"
    ).encode()
    source.write_bytes(data)
    output, report = run(TextMetadataConverter(True), source, tmp_path)
    cleaned = output.read_bytes()
    assert source.read_bytes() == data
    assert PRIVATE.encode() not in cleaned and b"\\b Visible\\b0" in cleaned and b"Arial" in cleaned
    assert b"\\{brace\\}" in cleaned
    assert PRIVATE not in report.read_text()


@pytest.mark.parametrize(
    "data",
    [
        rb"{\rtf1{\pict secret}}",
        rb"{\rtf1{\object secret}}",
        rb"{\rtf1{\*\unknown secret}}",
        rb"{\rtf1\bin4 {}}}",
        rb"{\rtf1\deleted hidden}",
        rb"{\rtf1 unclosed",
        rb"{\rtf1}trailer",
    ],
)
def test_complex_or_malformed_rtf_rejected(data):
    with pytest.raises(ConversionError):
        clean_rtf(data)


def test_neutral_text_does_not_claim_content_removal(tmp_path):
    source = tmp_path / "private.csv"
    source.write_text("author,formula\nPrivate visible,=SUM(1,2)\n", encoding="utf-16")
    output, report = run(TextMetadataConverter(), source, tmp_path)
    assert output.read_text(encoding="utf-8") == "author,formula\nPrivate visible,=SUM(1,2)\n"
    assert "private" not in output.name
    data = json.loads(report.read_text())
    assert "textual data unchanged" in data["policy"]


def test_external_excel_formula_and_hidden_rows_are_rejected(excel, tmp_path):
    book = load_workbook(excel)
    book.active["B1"] = '=WEBSERVICE("https://example.com/private")'
    book.save(excel)
    book.close()
    with pytest.raises(ConversionError, match="External spreadsheet"):
        run(OfficeMetadataConverter(FileFormat.XLSX), excel, tmp_path)
    book = load_workbook(excel)
    book.active["B1"] = "=1+2"
    book.active.row_dimensions[2].hidden = True
    book.save(excel)
    book.close()
    with pytest.raises(ConversionError, match="Hidden Excel"):
        run(OfficeMetadataConverter(FileFormat.XLSX), excel, tmp_path)


@pytest.mark.parametrize("kind", [FileFormat.DOCX, FileFormat.XLSX])
def test_collision_refuses_to_overwrite_office_files(tmp_path, kind, monkeypatch):
    from types import SimpleNamespace

    from local_pdf_toolkit.converters import office_metadata

    monkeypatch.setattr(office_metadata, "uuid4", lambda: SimpleNamespace(hex="a" * 32))
    source = tmp_path / ("source." + kind.value)
    if kind == FileFormat.DOCX:
        doc = Document()
        doc.add_paragraph("Visible")
        doc.save(source)
    else:
        book = Workbook()
        book.active["A1"] = "Visible"
        book.save(source)
        book.close()
    destination = tmp_path / ("clean-office-" + "a" * 12 + "." + kind.value)
    destination.write_bytes(b"keep")
    with pytest.raises(ConversionError):
        run(OfficeMetadataConverter(kind), source, tmp_path)
    assert destination.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_odf_formulas_keep_namespace_and_external_links_fail(tmp_path):
    path = tmp_path / "sheet.ods"
    make_odf(path, FileFormat.ODS)

    def formula(parts):
        tree = etree.fromstring(parts["content.xml"])
        cell = tree.find(".//{" + TABLE + "}table-cell")
        cell.set("{" + TABLE + "}formula", "of:=SUM([.A1:.A2])")
        parts["content.xml"] = etree.tostring(tree)

    change_zip(path, formula)
    result, _ = run(OdfMetadataConverter(), path, tmp_path)
    with zipfile.ZipFile(result) as package:
        root = etree.fromstring(package.read("content.xml"))
        cell = root.find(".//{" + TABLE + "}table-cell")
        assert cell.get("{" + TABLE + "}formula") == "of:=SUM([.A1:.A2])"
        assert cell.nsmap["of"] == "urn:oasis:names:tc:opendocument:xmlns:of:1.2"

    def external_formula(parts):
        tree = etree.fromstring(parts["content.xml"])
        cell = tree.find(".//{" + TABLE + "}table-cell")
        cell.set("{" + TABLE + "}formula", "of:=['../PrivateWorkbook.ods'#$Sheet1.A1]")
        parts["content.xml"] = etree.tostring(tree)

    change_zip(path, external_formula)
    original = path.read_bytes()
    rejected_output = tmp_path / "rejected"
    rejected_output.mkdir()
    with pytest.raises(ConversionError, match="External spreadsheet"):
        run(OdfMetadataConverter(), path, rejected_output)
    assert path.read_bytes() == original
    assert not list(rejected_output.iterdir())


def test_rtf_hidden_text_rejected():
    with pytest.raises(ConversionError):
        clean_rtf(rb"{\rtf1 \v Hidden private text\v0}")


@pytest.mark.parametrize(
    "kind",
    [
        FileFormat.DOCX,
        FileFormat.XLSX,
        FileFormat.ODT,
        FileFormat.ODS,
        FileFormat.ODP,
        FileFormat.RTF,
    ],
)
def test_cleaned_office_packages_open_in_real_libreoffice(tmp_path, kind):
    import pymupdf

    from local_pdf_toolkit.converters.office_pdf import OfficePdfConverter, find_libreoffice

    if find_libreoffice() is None:
        pytest.skip("LibreOffice is not installed")
    source = tmp_path / ("source." + kind.value)
    if kind == FileFormat.DOCX:
        doc = Document()
        doc.add_paragraph("Visible")
        doc.core_properties.author = PRIVATE
        doc.save(source)
        cleaner = OfficeMetadataConverter(kind)
    elif kind == FileFormat.XLSX:
        book = Workbook()
        book.active["A1"] = "Visible"
        book.properties.creator = PRIVATE
        book.save(source)
        book.close()
        cleaner = OfficeMetadataConverter(kind)
    elif kind == FileFormat.RTF:
        source.write_bytes(("{\\rtf1{\\info{\\author " + PRIVATE + "}} Visible}").encode())
        cleaner = TextMetadataConverter(rtf=True)
    else:
        make_odf(source, kind)
        cleaner = OdfMetadataConverter()
    cleaned, _ = run(cleaner, source, tmp_path)
    (output,) = OfficePdfConverter().convert(
        cleaned, tmp_path, {"timeout": 30}, lambda _: None, CancellationToken()
    )
    with pymupdf.open(output) as pdf:
        assert len(pdf) >= 1
        if kind != FileFormat.ODP:
            assert "Visible" in "".join(page.get_text() for page in pdf)
