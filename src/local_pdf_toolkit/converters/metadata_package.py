"""Bounded ZIP/XML primitives for the Office metadata cleaners."""

import json
import posixpath
import zipfile
from pathlib import Path

from lxml import etree

from local_pdf_toolkit.converters.pptx_metadata import _xml
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.output import OutputTransaction

MAX_BYTES = 512 * 1024 * 1024


def reject(message):
    raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, message)


def read_package(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        reject("Choose a regular Office package below 512 MiB.")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 20000 or sum(item.file_size for item in entries) > MAX_BYTES:
            reject("Office package exceeds size limits.")
        parts = {}
        seen = set()
        for entry in entries:
            name = entry.filename
            normalized = name.rstrip("/") if entry.is_dir() else name
            if (
                normalized.casefold() in seen
                or not normalized
                or "\\" in name
                or normalized.startswith("/")
                or ":" in name
                or posixpath.normpath(normalized) != normalized
                or entry.flag_bits & 1
            ):
                reject("Duplicate, encrypted or noncanonical package entries are unsupported.")
            seen.add(normalized.casefold())
            if entry.is_dir():
                continue
            if name.endswith((".xml", ".rels")) and entry.file_size > 64 * 1024 * 1024:
                reject("XML package part exceeds size limits.")
            parts[name] = archive.read(entry)
        return parts


def xml_bytes(root, namespaces=None):
    # Canonical prefixes keep Word's format detection interoperable without
    # retaining arbitrary source namespace labels. ODF can supply formula prefixes.
    if namespaces is None:
        ns = etree.QName(root).namespace
        if ns in (
            "http://schemas.openxmlformats.org/package/2006/content-types",
            "http://schemas.openxmlformats.org/package/2006/relationships",
        ):
            namespaces = {None: ns}
        else:
            namespaces = {
                "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
                "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
                "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
                "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
                "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
                "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
            }

    def clone(node, top=False):
        result = etree.Element(node.tag, nsmap=namespaces if top else None)
        result.attrib.update(node.attrib)
        result.text, result.tail = node.text, node.tail
        for child in node:
            result.append(clone(child))
        return result

    return etree.tostring(clone(root, True), encoding="UTF-8", xml_declaration=True)


def write_package(parts, path, token, mimetype=None):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as output:
        names = sorted(parts)
        if mimetype is not None:
            names.remove("mimetype")
            names.insert(0, "mimetype")
        for name in names:
            token.raise_if_cancelled()
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 0
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            output.writestr(info, parts[name])


def publish_package(parts, output_dir, name, report, token, verify, mimetype=None):
    report_name = Path(name).stem + ".report.json"
    with OutputTransaction(Path(output_dir)) as output:
        path = output.staging / name
        write_package(parts, path, token, mimetype)
        verify(path)
        (output.staging / report_name).write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return output.publish([name, report_name], token)


def translate_errors(function):
    """Normalize container/parser failures without including private document values."""
    from functools import wraps

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ConversionError:
            raise
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED,
                "Cannot parse, clean or save this Office file. Check the format, "
                "permissions and existing outputs.",
            ) from exc

    return wrapped


def parse_xml_parts(parts):
    return {name: _xml(data) for name, data in parts.items() if name.endswith((".xml", ".rels"))}
