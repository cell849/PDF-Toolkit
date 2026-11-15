"""Hand-authored Office ZIP/XML fixtures with independently specified expected content."""

import struct
import xml.etree.ElementTree as ET
import zipfile

import pytest

from local_pdf_toolkit.converters.office_metadata import OfficeMetadataConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.formats import FileFormat

from .independent_pdf import sha256

CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def write_office(path, kind):
    if kind == FileFormat.DOCX:
        main_name = "word/document.xml"
        main_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        )
        main = (
            f'<w:document xmlns:w="{WORD}"><w:body><w:p><w:r><w:rPr><w:b/></w:rPr>'
            '<w:t>PUBLIC-TEXT</w:t></w:r><w:ins w:id="1" w:author="SECRET-REVIEWER">'
            '<w:r><w:t>ADDED-TEXT</w:t></w:r></w:ins><w:del w:id="2">'
            "<w:r><w:delText>SECRET-DELETED</w:delText></w:r></w:del></w:p>"
            '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>'
        )
        extra = {}
    else:
        main_name = "xl/workbook.xml"
        main_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
        main = (
            f'<s:workbook xmlns:s="{SHEET}" xmlns:r="{OFFICE_REL}"><s:sheets>'
            '<s:sheet name="Ledger" sheetId="1" r:id="rIdWorksheet"/></s:sheets>'
            '<s:definedNames><s:definedName name="Rate">Ledger!$B$1</s:definedName>'
            "</s:definedNames></s:workbook>"
        )
        extra = {
            "xl/_rels/workbook.xml.rels": (
                f'<Relationships xmlns="{RELATIONSHIPS}"><Relationship Id="rIdWorksheet" '
                f'Type="{OFFICE_REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
            ),
            "xl/worksheets/sheet1.xml": (
                f'<s:worksheet xmlns:s="{SHEET}"><s:sheetData><s:row r="1">'
                '<s:c r="A1" t="inlineStr"><s:is><s:t>PUBLIC-TEXT</s:t></s:is></s:c>'
                '<s:c r="B1"><s:f>SUM(1,2)</s:f><s:v>3</s:v></s:c>'
                "</s:row></s:sheetData></s:worksheet>"
            ),
        }
    parts = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CONTENT_TYPES}"><Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/{main_name}" ContentType="{main_type}"/></Types>'
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{RELATIONSHIPS}"><Relationship Id="main" '
            f'Type="{OFFICE_REL}/officeDocument" Target="{main_name}"/>'
            '<Relationship Id="properties" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/'
            'metadata/core-properties" '
            'Target="docProps/core.xml"/></Relationships>'
        ),
        main_name: main,
        "docProps/core.xml": "<properties><author>SECRET-AUTHOR</author></properties>",
        **extra,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b"SECRET-ARCHIVE-COMMENT"
        for name, data in parts.items():
            info = zipfile.ZipInfo(name)
            info.comment = b"SECRET-MEMBER-COMMENT"
            value = b"SECRET-EXTRA-FIELD"
            info.extra = struct.pack("<HH", 0xCAFE, len(value)) + value
            archive.writestr(info, data.encode())
    return path


@pytest.mark.parametrize("kind", [FileFormat.DOCX, FileFormat.XLSX])
def test_office_cleaner_preserves_content_and_removes_package_metadata(tmp_path, kind):
    source = write_office(tmp_path / ("SECRET-SOURCE." + kind.value), kind)
    before = sha256(source)
    output, report = OfficeMetadataConverter(kind).convert(
        source, tmp_path, {}, lambda _: None, CancellationToken()
    )
    with zipfile.ZipFile(output) as archive:
        assert not archive.comment
        assert archive.testzip() is None
        assert not any(name.startswith("docProps/") for name in archive.namelist())
        for member in archive.infolist():
            assert not member.comment and not member.extra
            assert member.date_time == (1980, 1, 1, 0, 0, 0)
            assert "SECRET" not in member.filename
            assert b"SECRET" not in archive.read(member)
        if kind == FileFormat.DOCX:
            root = ET.fromstring(archive.read("word/document.xml"))
            assert [node.text for node in root.iter("{" + WORD + "}t")] == [
                "PUBLIC-TEXT",
                "ADDED-TEXT",
            ]
            assert next(root.iter("{" + WORD + "}b"), None) is not None
            assert not list(root.iter("{" + WORD + "}ins"))
            assert not list(root.iter("{" + WORD + "}del"))
        else:
            root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            assert next(root.iter("{" + SHEET + "}t")).text == "PUBLIC-TEXT"
            assert next(root.iter("{" + SHEET + "}f")).text == "SUM(1,2)"
            assert next(root.iter("{" + SHEET + "}v")).text == "3"
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            assert next(workbook.iter("{" + SHEET + "}sheet")).get("name") == "Ledger"
            assert next(workbook.iter("{" + SHEET + "}definedName")).text == "Ledger!$B$1"
    assert "SECRET" not in report.read_text()
    assert "SECRET" not in output.name and "SECRET" not in report.name
    assert sha256(source) == before
