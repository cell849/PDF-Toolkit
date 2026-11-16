"""Optional, local LibreOffice conversion of a deliberately restricted document set.

This is format validation and a hardened profile, not a document sandbox. HTML,
legacy binary Office and macro-enabled documents are intentionally unsupported.
"""

import contextlib
import csv
import io
import os
import posixpath
import re
import shutil
import signal
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from local_pdf_toolkit.converters.pdf_images import MAX_INPUT_BYTES, PdfImagesConverter
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

_FORMATS = ("docx", "xlsx", "pptx", "odt", "ods", "odp", "rtf", "txt", "csv")
_OOXML_ROOTS = {
    "docx": ("word/document.xml", "document"),
    "xlsx": ("xl/workbook.xml", "workbook"),
    "pptx": ("ppt/presentation.xml", "presentation"),
}
_ODF_MIMES = {
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
}
_UNSAFE_FORMULA = re.compile(r"(?:WEBSERVICE|HYPERLINK|RTD|DDE|IMAGE)\s*\(|\[", re.I)


def find_libreoffice():
    """Find an installed binary without executing a shell or searching documents."""
    for binary in ("soffice", "libreoffice", "soffice.exe"):
        if found := shutil.which(binary):
            return Path(found)
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(variable)
            if base:
                candidate = Path(base) / "LibreOffice" / "program" / "soffice.exe"
                if candidate.is_file():
                    return candidate
    return None


def _invalid(message):
    raise ConversionError(ErrorCode.INVALID_INPUT, message)


def _xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        _invalid("XML document types and entities are unsupported.")
    return ET.fromstring(data)


def _text(path):
    data = path.read_bytes()
    encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    text = data.decode(encoding)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        _invalid("Text input contains binary control characters.")
    return text


def _validate_package(path, kind):
    with zipfile.ZipFile(path) as package:
        entries = package.infolist()
        if len(entries) > 20000 or sum(item.file_size for item in entries) > MAX_INPUT_BYTES:
            _invalid("Office package exceeds safe size limits.")
        names = set(package.namelist())
        if len(names) != len(entries) or any(item.flag_bits & 1 for item in entries):
            _invalid("Duplicate or encrypted Office package entries are unsupported.")
        if any(
            "vba" in name.lower()
            or "/embeddings/" in name.lower()
            or name.lower().endswith((".html", ".htm", ".mht", ".mhtml", ".svg", ".js"))
            or name.lower().startswith(("basic/", "scripts/"))
            for name in names
        ):
            _invalid("Macros, active content and embedded documents are unsupported.")
        if kind in _OOXML_ROOTS:
            main, tag = _OOXML_ROOTS[kind]
            root = _xml(package.read(main))
            if (
                root.tag.rsplit("}", 1)[-1] != tag
                or not root.tag.startswith("{http://schemas.openxmlformats.org/")
                or "[Content_Types].xml" not in names
            ):
                _invalid("Office package does not match its format.")
        elif package.read("mimetype").decode("ascii") != _ODF_MIMES[kind]:
            _invalid("OpenDocument package does not match its format.")
        for name in names:
            if not name.endswith((".xml", ".rels")):
                continue
            root = _xml(package.read(name))
            for element in root.iter():
                local = element.tag.rsplit("}", 1)[-1]
                if local in (
                    "encryption-data",
                    "script",
                    "scripts",
                    "event-listener",
                    "externalLink",
                    "ddeLink",
                    "oleLink",
                    "attachedTemplate",
                    "altChunk",
                    "dde-link",
                    "dde-links",
                    "object-ole",
                ):
                    _invalid("Encrypted content and scripts are unsupported.")
                if element.attrib.get("TargetMode", "").lower() == "external":
                    _invalid("External document links are unsupported for offline conversion.")
                if local == "Relationship":
                    target = unquote(element.attrib.get("Target", "")).split("#", 1)[0]
                    if re.match(r"(?:[a-zA-Z][a-zA-Z0-9+.-]*:|\\)", target):
                        _invalid("External document links are unsupported.")
                    base = str(PurePosixPath(name).parent.parent)
                    member = posixpath.normpath(
                        target.lstrip("/")
                        if target.startswith("/")
                        else posixpath.join(base, target)
                    )
                    if member not in names:
                        _invalid("Missing or external Office relationship target.")
                for key, value in element.attrib.items():
                    if key.rsplit("}", 1)[-1] == "href":
                        target = value.removeprefix("./").split("#", 1)[0]
                        if (
                            target
                            and target not in names
                            and not any(
                                member.startswith(target.rstrip("/") + "/") for member in names
                            )
                        ):
                            _invalid("External document links are unsupported.")
                    if key.rsplit("}", 1)[-1] == "formula" and _UNSAFE_FORMULA.search(value):
                        _invalid("External spreadsheet formulas are unsupported.")
                if local in ("f", "definedName") and _UNSAFE_FORMULA.search(element.text or ""):
                    _invalid("External spreadsheet formulas are unsupported.")
                if local in ("instrText", "fldSimple") and re.search(
                    r"\b(DDE|DDEAUTO|INCLUDETEXT|INCLUDEPICTURE|DATABASE|LINK)\b",
                    " ".join(element.attrib.values()) + (element.text or ""),
                    re.I,
                ):
                    _invalid("External document fields are unsupported.")
        if kind in _ODF_MIMES:
            root = _xml(package.read("content.xml"))
            if root.tag != "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}document-content":
                _invalid("Invalid OpenDocument content.")


def _profile(directory):
    user = directory / "user"
    user.mkdir(parents=True)
    # Macro security very high; never refresh linked content. Reject such content
    # at validation as well, because configuration is not a network sandbox.
    (user / "registrymodifications.xcu").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
        '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
        '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>'
        '<item oor:path="/org.openoffice.Office.Common/Load">'
        '<prop oor:name="UpdateDocMode" oor:op="fuse"><value>0</value></prop></item>'
        '<item oor:path="/org.openoffice.Office.Writer/Content/Update">'
        '<prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>'
        '<item oor:path="/org.openoffice.Office.Calc/Content/Update">'
        '<prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item>'
        "</oor:items>",
        encoding="utf-8",
    )


def _run(command, timeout, cancel_token):
    """Poll cancellation and reap LibreOffice on every exit path."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            cancel_token.raise_if_cancelled()
            if time.monotonic() >= deadline:
                raise ConversionError(
                    ErrorCode.CONVERSION_FAILED, "LibreOffice conversion timed out."
                )
            time.sleep(0.05)
        cancel_token.raise_if_cancelled()
        if process.returncode:
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "LibreOffice conversion failed.")
    finally:
        if process.poll() is None:
            if os.name == "nt":
                # soffice.exe may supervise soffice.bin; terminate its whole tree.
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.kill()
                else:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        else:
            process.wait()
        if os.name != "nt":
            # A supervisor can also exit normally before its descendants finish.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)


class OfficePdfConverter:
    def __init__(self):
        self.spec = ConverterSpec(
            "office.to_pdf",
            "Office / text to PDF (LibreOffice)",
            tuple(FileFormat(kind) for kind in _FORMATS),
            (FileFormat.PDF,),
            (
                OptionDefinition(
                    "timeout",
                    "Timeout (seconds)",
                    120,
                    "Maximum LibreOffice conversion time.",
                    minimum=5,
                    maximum=600,
                ),
            ),
            (
                "Requires a separately installed LibreOffice; fonts and layouts may change.",
                "Macros, embedded documents, external links, HTML and legacy Office "
                "are unsupported.",
                "UTF-8 / UTF-16 text only; CSV values are imported as literal text.",
            ),
        )

    def validate_options(self, options):
        timeout = options.get("timeout", 120)
        if set(options) - {"timeout"} or type(timeout) is not int or not 5 <= timeout <= 600:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Timeout must be 5–600 seconds.")
        return {"timeout": timeout}

    def validate_input(self, input_path):
        path = Path(input_path)
        kind = path.suffix.lower().lstrip(".")
        if kind not in _FORMATS:
            raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, "Unsupported Office/text format.")
        try:
            if not path.is_file() or not 0 < path.stat().st_size <= MAX_INPUT_BYTES:
                _invalid("Choose a nonempty Office/text file no larger than 512 MiB.")
            if kind in (*_OOXML_ROOTS, *_ODF_MIMES):
                _validate_package(path, kind)
            elif kind in ("txt", "csv"):
                content = _text(path)
                if kind == "csv":
                    for row in csv.reader(io.StringIO(content), strict=True):
                        if len(row) > 16384:
                            _invalid("CSV exceeds spreadsheet column limits.")
            else:
                data = path.read_bytes()
                if not data.startswith(b"{\\rtf") or re.search(
                    rb"\\(?:object|objdata|field|filetbl|datastore|htmltag|htmlrtf|bin)\b",
                    data,
                    re.I,
                ):
                    _invalid("Invalid RTF or unsupported embedded/external RTF content.")
                # Ignore escaped braces and hex literals when checking group structure.
                groups = re.sub(rb"\\(?:[{}\\]|'[0-9a-fA-F]{2})", b"", data)
                depth = 0
                for byte in groups:
                    depth += (byte == 123) - (byte == 125)
                    if depth < 0:
                        _invalid("Invalid RTF group structure.")
                if depth or not data.rstrip().endswith(b"}"):
                    _invalid("Invalid RTF group structure.")
            return FileFormat(kind)
        except (
            OSError,
            ValueError,
            KeyError,
            zipfile.BadZipFile,
            ET.ParseError,
            UnicodeError,
            csv.Error,
        ) as exc:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "Cannot parse the Office/text document."
            ) from exc

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        options = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        kind = self.validate_input(input_path)
        binary = find_libreoffice()
        if binary is None:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED,
                "LibreOffice is not installed. Install it locally to use this tool.",
            )
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(input_path).stem).rstrip(" .")[:100]
        name = f"{stem or 'document'}.pdf"
        try:
            with (
                OutputTransaction(Path(output_dir)) as outputs,
                tempfile.TemporaryDirectory(prefix="pdf-toolkit-office-") as temporary,
            ):
                if (outputs.directory / name).exists():
                    raise ConversionError(ErrorCode.OUTPUT_ERROR, "Output already exists.")
                work = Path(temporary)
                source = work / ("source." + kind.value)
                shutil.copyfile(input_path, source)
                # Validate the snapshot actually passed to the external process.
                self.validate_input(source)
                if kind == FileFormat.CSV:
                    # XLSX literal string cells avoid spreadsheet formula execution.
                    from openpyxl import Workbook

                    workbook = Workbook(write_only=False)
                    sheet = workbook.active
                    for row_index, row in enumerate(csv.reader(io.StringIO(_text(source))), 1):
                        cancel_token.raise_if_cancelled()
                        if row_index > 1048576:
                            _invalid("CSV exceeds spreadsheet row limits.")
                        for column, value in enumerate(row, 1):
                            if len(value) > 32767:
                                _invalid("CSV cell exceeds the spreadsheet text length limit.")
                            cell = sheet.cell(row_index, column, value)
                            cell.data_type = "s"
                    source = work / "source.xlsx"
                    workbook.save(source)
                    workbook.close()
                profile = work / "profile"
                _profile(profile)
                progress(Progress())
                command = [
                    str(binary),
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--invisible",
                    "--nologo",
                    "--nodefault",
                    "--norestore",
                    "--nofirststartwizard",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(outputs.staging),
                    str(source),
                ]
                if kind == FileFormat.TXT:
                    # Prevent HTML-looking text from triggering automatic HTML import.
                    command.insert(-1, "--infilter=Text")
                _run(command, options["timeout"], cancel_token)
                produced = outputs.staging / "source.pdf"
                try:
                    with PdfImagesConverter(FileFormat.PNG)._open(produced):
                        pass
                except ConversionError as exc:
                    raise ConversionError(
                        ErrorCode.CONVERSION_FAILED,
                        "LibreOffice did not produce a valid PDF for this document.",
                    ) from exc
                produced.rename(outputs.staging / name)
                cancel_token.raise_if_cancelled()
                result = outputs.publish([name], cancel_token)
                progress(Progress(1, 1))
                return result
        except ImportError as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "CSV conversion requires the openpyxl package."
            ) from exc
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR, "Cannot run LibreOffice or write the output PDF."
            ) from exc


def office_converters():
    return (OfficePdfConverter(),)
