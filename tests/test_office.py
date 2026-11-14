"""Real document fixtures plus local subprocess and failure-path checks."""

import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import docx
import openpyxl
import pptx
import pymupdf
import pytest

from local_pdf_toolkit.converters import office_pdf, pdf_office
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


@pytest.fixture
def text_pdf(tmp_path):
    path = tmp_path / "words.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((40, 60), "Selectable text, first page")
        document.new_page().insert_text((40, 60), "Second page")
        document.save(path)
    return path


@pytest.fixture
def table_pdf(tmp_path):
    path = tmp_path / "table.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        for x in (40, 180, 320):
            page.draw_line((x, 40), (x, 160))
        for y in (40, 80, 120, 160):
            page.draw_line((40, y), (320, y))
        for row, cells in enumerate((("Name", "Value"), ("Apple", "12"), ("=2+2", "4"))):
            for col, text in enumerate(cells):
                page.insert_text((50 + col * 140, 65 + row * 40), text)
        document.save(path)
    return path


def convert(kind, source, output, options=None, progress=None, token=None):
    output.mkdir(exist_ok=True)
    return pdf_office.PdfOfficeConverter(kind).convert(
        source, output, options or {}, progress or (lambda _: None), token or CancellationToken()
    )


def test_docx_selectable_text_and_page_selection(text_pdf, tmp_path):
    (result,) = convert(FileFormat.DOCX, text_pdf, tmp_path / "out", {"pages": "2"})
    paragraphs = [paragraph.text for paragraph in docx.Document(result).paragraphs]
    assert paragraphs == ["Second page"]
    assert text_pdf.is_file()


def test_xlsx_detects_actual_table_and_writes_literal_strings(table_pdf, tmp_path):
    (result,) = convert(FileFormat.XLSX, table_pdf, tmp_path / "out")
    with result.open("rb") as stream:
        workbook = openpyxl.load_workbook(stream)
        assert workbook.sheetnames == ["Page 1 Table 1"]
        assert list(workbook.active.values) == [("Name", "Value"), ("Apple", "12"), ("=2+2", "4")]
        assert workbook.active["A3"].data_type == "s"
        workbook.close()


def test_xlsx_no_table_does_not_fabricate_workbook(text_pdf, tmp_path):
    output = tmp_path / "out"
    with pytest.raises(ConversionError, match="No tables detected"):
        convert(FileFormat.XLSX, text_pdf, output)
    assert list(output.iterdir()) == []


def test_pptx_pages_are_images_and_count_matches_selection(text_pdf, tmp_path):
    (result,) = convert(FileFormat.PPTX, text_pdf, tmp_path / "out", {"dpi": 72})
    presentation = pptx.Presentation(result)
    assert len(presentation.slides) == 2
    for slide in presentation.slides:
        assert len(slide.shapes) == 1
        assert slide.shapes[0].image.content_type == "image/png"
    assert "not editable" in pdf_office.PdfOfficeConverter(FileFormat.PPTX).spec.limitations[0]


@pytest.mark.parametrize("kind", [FileFormat.DOCX, FileFormat.XLSX, FileFormat.PPTX])
def test_cancel_after_first_page_removes_staged_office_output(kind, text_pdf, tmp_path):
    output = tmp_path / "out"
    token = CancellationToken()

    def progress(value):
        if value.completed:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        convert(kind, text_pdf, output, progress=progress, token=token)
    assert list(output.iterdir()) == []


def test_docx_no_text_is_honest(tmp_path):
    source = tmp_path / "blank.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(source)
    with pytest.raises(ConversionError, match="No selectable text"):
        convert(FileFormat.DOCX, source, tmp_path / "out")


def test_dependency_error_is_actionable(text_pdf, tmp_path, monkeypatch):
    def missing(_):
        raise ImportError()

    monkeypatch.setattr(pdf_office.importlib, "import_module", missing)
    with pytest.raises(ConversionError, match="python-docx"):
        convert(FileFormat.DOCX, text_pdf, tmp_path / "out")


def test_pdf_export_encrypted_malformed_and_collision(text_pdf, tmp_path):
    output = tmp_path / "out"
    (result,) = convert(FileFormat.DOCX, text_pdf, output)
    original = result.read_bytes()
    with pytest.raises(ConversionError) as error:
        convert(FileFormat.DOCX, text_pdf, output)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert result.read_bytes() == original
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7 invalid")
    with pytest.raises(ConversionError):
        convert(FileFormat.DOCX, broken, output)
    encrypted = tmp_path / "encrypted.pdf"
    with pymupdf.open(text_pdf) as document:
        document.save(encrypted, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    with pytest.raises(ConversionError) as error:
        convert(FileFormat.DOCX, encrypted, output)
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED


def test_office_validates_real_docx_xlsx_pptx_and_text(tmp_path):
    sources = []
    source = tmp_path / "sample.docx"
    document = docx.Document()
    document.add_paragraph("Hello")
    document.save(source)
    sources.append(source)
    source = tmp_path / "sample.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "Hello"
    workbook.save(source)
    workbook.close()
    sources.append(source)
    source = tmp_path / "sample.pptx"
    presentation = pptx.Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    presentation.save(source)
    sources.append(source)
    for kind, data in (
        ("txt", b"hello"),
        ("csv", b"Name,Value\nApple,12\n"),
        ("rtf", b"{\\rtf1 hello}"),
    ):
        source = tmp_path / ("sample." + kind)
        source.write_bytes(data)
        sources.append(source)
    converter = office_pdf.OfficePdfConverter()
    for source in sources:
        assert converter.validate_input(source).value == source.suffix[1:]


def test_office_rejects_fake_package_external_links_macros_and_rtf_fields(tmp_path):
    converter = office_pdf.OfficePdfConverter()
    fake = tmp_path / "fake.docx"
    fake.write_text("not a package")
    with pytest.raises(ConversionError):
        converter.validate_input(fake)
    real = tmp_path / "unsafe.docx"
    document = docx.Document()
    document.add_paragraph("Hello")
    document.save(real)
    with zipfile.ZipFile(real, "a") as package:
        package.writestr(
            "word/_rels/evil.xml.rels",
            "<Relationships><Relationship "
            'TargetMode="External" Target="https://example.com/data"/></Relationships>',
        )
    with pytest.raises(ConversionError, match="External"):
        converter.validate_input(real)
    macro = tmp_path / "macro.docx"
    document.save(macro)
    with zipfile.ZipFile(macro, "a") as package:
        package.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(ConversionError, match="Macros"):
        converter.validate_input(macro)
    rtf = tmp_path / "unsafe.rtf"
    rtf.write_bytes(b"{\\rtf1{\\field external}}")
    with pytest.raises(ConversionError, match="RTF"):
        converter.validate_input(rtf)
    html = tmp_path / "page.html"
    html.write_text('<img src="https://example.com/a.png">')
    with pytest.raises(ConversionError) as error:
        converter.validate_input(html)
    assert error.value.code == ErrorCode.UNSUPPORTED_FORMAT


def test_missing_libreoffice_and_precancel_do_not_write(tmp_path, monkeypatch):
    source = tmp_path / "sample.txt"
    source.write_text("Hello")
    monkeypatch.setattr(office_pdf, "find_libreoffice", lambda: None)
    converter = office_pdf.OfficePdfConverter()
    with pytest.raises(ConversionError, match="LibreOffice is not installed"):
        converter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConversionCancelled):
        converter.convert(source, tmp_path, {}, lambda _: None, token)
    assert list(tmp_path.iterdir()) == [source]


def test_subprocess_cancel_reaps_child(monkeypatch):
    real_popen = subprocess.Popen
    children = []

    def tracked(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(office_pdf.subprocess, "Popen", tracked)
    token = CancellationToken()
    timer = threading.Timer(0.15, token.cancel)
    timer.start()
    try:
        with pytest.raises(ConversionCancelled):
            office_pdf._run([sys.executable, "-c", "import time; time.sleep(30)"], 10, token)
    finally:
        timer.cancel()
    assert len(children) == 1 and children[0].poll() is not None


def test_subprocess_timeout_reaps_child():
    started = time.monotonic()
    with pytest.raises(ConversionError, match="timed out"):
        office_pdf._run(
            [sys.executable, "-c", "import time; time.sleep(30)"], 0.1, CancellationToken()
        )
    assert time.monotonic() - started < 5


def test_mocked_office_conversion_uses_profile_and_safe_transaction(tmp_path, monkeypatch):
    source = tmp_path / "invoice.txt"
    source.write_text("Hello")
    output = tmp_path / "out"
    output.mkdir()
    monkeypatch.setattr(office_pdf, "find_libreoffice", lambda: Path("/local/soffice"))

    def fake_run(command, timeout, token):
        assert "--headless" in command and "--norestore" in command
        assert timeout == 120
        profile_url = next(
            argument.split("=", 1)[1]
            for argument in command
            if argument.startswith("-env:UserInstallation=")
        )
        from urllib.parse import unquote, urlparse

        profile = Path(unquote(urlparse(profile_url).path))
        assert "MacroSecurityLevel" in (profile / "user/registrymodifications.xcu").read_text()
        staging = Path(command[command.index("--outdir") + 1])
        with pymupdf.open() as document:
            document.new_page().insert_text((40, 60), "Converted locally")
            document.save(staging / "source.pdf")

    monkeypatch.setattr(office_pdf, "_run", fake_run)
    (result,) = office_pdf.OfficePdfConverter().convert(
        source, output, {}, lambda _: None, CancellationToken()
    )
    assert result.name == "invoice.pdf"
    with pymupdf.open(result) as document:
        assert "Converted locally" in document[0].get_text()
    assert source.read_text() == "Hello"
    assert list(output.iterdir()) == [result]


@pytest.mark.skipif(office_pdf.find_libreoffice() is None, reason="LibreOffice is not installed")
@pytest.mark.parametrize("kind", ["docx", "xlsx", "pptx", "txt", "csv", "rtf"])
def test_real_libreoffice_to_pdf(tmp_path, kind):
    source = tmp_path / ("example." + kind)
    text = "Local LibreOffice integration"
    if kind == "docx":
        document = docx.Document()
        document.add_paragraph(text)
        document.save(source)
    elif kind == "xlsx":
        document = openpyxl.Workbook()
        document.active["A1"] = text
        document.save(source)
        document.close()
    elif kind == "pptx":
        document = pptx.Presentation()
        slide = document.slides.add_slide(document.slide_layouts[6])
        slide.shapes.add_textbox(100000, 100000, 7000000, 1000000).text = text
        document.save(source)
    else:
        source.write_text("{\\rtf1 " + text + "}" if kind == "rtf" else text)
    output = tmp_path / "out"
    output.mkdir()
    (result,) = office_pdf.OfficePdfConverter().convert(
        source, output, {}, lambda _: None, CancellationToken()
    )
    with pymupdf.open(result) as document:
        assert text in " ".join(page.get_text() for page in document)


def odf_fixture(path, kind):
    body = {
        "odt": "<office:text><text:p>OpenDocument fixture</text:p></office:text>",
        "ods": '<office:spreadsheet><table:table table:name="Sheet1"><table:table-row>'
        '<table:table-cell office:value-type="string"><text:p>OpenDocument fixture</text:p>'
        "</table:table-cell></table:table-row></table:table></office:spreadsheet>",
        "odp": '<office:presentation><draw:page draw:name="Page1"><draw:frame '
        'svg:x="1cm" svg:y="1cm" svg:width="20cm" svg:height="5cm">'
        "<draw:text-box><text:p>OpenDocument fixture</text:p></draw:text-box>"
        "</draw:frame></draw:page></office:presentation>",
    }[kind]
    content = (
        '<?xml version="1.0"?>'
        '<office:document-content office:version="1.2" '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
        'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0">'
        "<office:body>" + body + "</office:body></office:document-content>"
    )
    mime = office_pdf._ODF_MIMES[kind]
    manifest = (
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
        '<manifest:file-entry manifest:full-path="/" manifest:media-type="' + mime + '"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("mimetype", mime)
        package.writestr("content.xml", content)
        package.writestr("META-INF/manifest.xml", manifest)


@pytest.mark.parametrize("kind", ["odt", "ods", "odp"])
def test_opendocument_package_verification(tmp_path, kind):
    source = tmp_path / ("fixture." + kind)
    odf_fixture(source, kind)
    assert office_pdf.OfficePdfConverter().validate_input(source) == FileFormat(kind)
    with zipfile.ZipFile(source, "a") as package:
        package.writestr("unsafe.xml", "<root><script/></root>")
    with pytest.raises(ConversionError, match="scripts"):
        office_pdf.OfficePdfConverter().validate_input(source)


@pytest.mark.skipif(office_pdf.find_libreoffice() is None, reason="LibreOffice is not installed")
@pytest.mark.parametrize("kind", ["odt", "ods", "odp"])
def test_real_libreoffice_opendocument(tmp_path, kind):
    source = tmp_path / ("fixture." + kind)
    odf_fixture(source, kind)
    output = tmp_path / "out"
    output.mkdir()
    (result,) = office_pdf.OfficePdfConverter().convert(
        source, output, {}, lambda _: None, CancellationToken()
    )
    with pymupdf.open(result) as document:
        assert "OpenDocument fixture" in " ".join(page.get_text() for page in document)
