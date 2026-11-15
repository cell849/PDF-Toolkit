"""Conservative, editable PPTX metadata removal; unsupported payloads fail closed.

Visible slide content is intentionally retained. This is not anonymization.
"""

import io
import json
import posixpath
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from lxml import etree
from PIL import Image

from local_pdf_toolkit.core.contracts import ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_BYTES = 512 * 1024 * 1024
MAX_PARTS = 20_000
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML = "http://www.w3.org/XML/1998/namespace"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
SUPPORTED_XML = re.compile(
    r"ppt/(?:presentation|tableStyles)\.xml|"
    r"ppt/(?:slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster|theme/theme)\d+\.xml"
)
REMOVED_PREFIXES = (
    "docProps/",
    "ppt/notesSlides/",
    "ppt/notesMasters/",
    "ppt/comments/",
    "ppt/persons/",
    "ppt/tags/",
    "ppt/printerSettings/",
)
REMOVED_FILES = {"ppt/commentAuthors.xml", "ppt/viewProps.xml", "ppt/presProps.xml"}
MEDIA_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


def _fail(message):
    raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, message)


def _xml(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        _fail("XML entities and document types are unsupported.")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=True, remove_pis=True
    )
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype:
        _fail("XML document types are unsupported.")
    return root


def _serialized(root):
    namespaces = {"p": P, "a": A, "r": R, "mc": MC, "pr": PKG, "ct": CT}

    def clone(node, top=False):
        result = etree.Element(node.tag, nsmap=namespaces if top else None)
        result.attrib.update(node.attrib)
        result.text = node.text
        result.tail = node.tail
        for child in node:
            result.append(clone(child))
        return result

    normalized = clone(root, True)
    etree.cleanup_namespaces(normalized)
    return etree.tostring(normalized, encoding="UTF-8", xml_declaration=True, standalone=True)


def _source_for_relationship(name):
    if name == "_rels/.rels":
        return ""
    folder, filename = name.rsplit("/_rels/", 1)
    return folder + "/" + filename.removesuffix(".rels")


def _target(source, value):
    decoded = unquote(value).split("#", 1)[0]
    if not decoded or "\\" in decoded or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", decoded):
        _fail("Invalid or external relationship target.")
    path = posixpath.normpath(
        decoded.lstrip("/")
        if decoded.startswith("/")
        else posixpath.join(posixpath.dirname(source), decoded)
    )
    if path == ".." or path.startswith("../"):
        _fail("Relationship escapes the presentation package.")
    return path


def _read_package(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a PPTX no larger than 512 MiB.")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > MAX_PARTS or sum(entry.file_size for entry in entries) > MAX_BYTES:
            _fail("PPTX package exceeds resource limits.")
        if len(set(names)) != len(names) or len({name.casefold() for name in names}) != len(names):
            _fail("Duplicate package paths are unsupported.")
        for entry in entries:
            name = entry.filename
            if (
                entry.flag_bits & 1
                or name.startswith("/")
                or "\\" in name
                or posixpath.normpath(name) != name
                or ":" in name
                or entry.is_dir()
            ):
                _fail("Encrypted, directory or noncanonical package entries are unsupported.")
            if entry.file_size > 64 * 1024 * 1024 and name.endswith((".xml", ".rels")):
                _fail("XML package part exceeds resource limits.")
        parts = {name: archive.read(name) for name in names}
    if not {"[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml"} <= parts.keys():
        raise ConversionError(ErrorCode.INVALID_INPUT, "This is not a supported PPTX package.")
    if _xml(parts["ppt/presentation.xml"]).tag != f"{{{P}}}presentation":
        _fail("Only standard PPTX presentations are supported.")
    return parts


def _clean_parts(parts, token, progress):
    from local_pdf_toolkit.converters.image_metadata import clean_image_bytes

    removed = {name for name in parts if name.startswith(REMOVED_PREFIXES) or name in REMOVED_FILES}
    remaining = set(parts) - removed
    for name in remaining:
        if name in ("[Content_Types].xml", "_rels/.rels") or SUPPORTED_XML.fullmatch(name):
            continue
        if "/_rels/" in name and name.endswith(".rels"):
            source = _source_for_relationship(name)
            if source not in parts:
                _fail("Relationship part has no owning document part.")
            if source in removed:
                removed.add(name)
            continue
        if name.startswith("ppt/media/") and Path(name).suffix.lower() in MEDIA_EXTENSIONS:
            continue
        _fail(
            "This PPTX contains unsupported parts (for example embedded files, fonts, "
            "charts, SmartArt, macros, signatures, or non-raster media). No output was cleaned."
        )
    remaining -= removed
    media_names = {
        name: f"ppt/media/image{index:04d}{Path(name).suffix.lower()}"
        for index, name in enumerate(sorted(n for n in remaining if n.startswith("ppt/media/")), 1)
    }
    rels = {}
    retained_ids = {}
    removed_ids = {}
    for name in sorted(remaining):
        token.raise_if_cancelled()
        if not name.endswith(".rels"):
            continue
        root = _xml(parts[name])
        if root.tag != f"{{{PKG}}}Relationships":
            _fail("Invalid relationship XML.")
        source = _source_for_relationship(name)
        removed_ids[source] = set()
        retained_ids[source] = {}
        root.attrib.clear()
        seen = set()
        for relation in list(root):
            if (
                relation.tag != f"{{{PKG}}}Relationship"
                or not relation.get("Id")
                or relation.get("Id") in seen
            ):
                _fail("Invalid or duplicate relationship identifier.")
            seen.add(relation.get("Id"))
            if relation.get("TargetMode", "").lower() == "external":
                _fail("External links are unsupported. Remove them in PowerPoint first.")
            destination = _target(source, relation.get("Target", ""))
            if destination not in parts:
                _fail("A relationship refers to a missing package part.")
            if destination in removed:
                removed_ids[source].add(relation.get("Id"))
                root.remove(relation)
            else:
                kind = relation.get("Type", "")
                if not kind.startswith(R + "/") or kind.rsplit("/", 1)[-1] not in {
                    "officeDocument",
                    "slide",
                    "slideLayout",
                    "slideMaster",
                    "theme",
                    "tableStyles",
                    "image",
                    "hyperlink",
                }:
                    _fail("Unsupported relationship type remains in the presentation.")
                new_id = f"rId{len(retained_ids[source]) + 1}"
                retained_ids[source][relation.get("Id")] = new_id
                destination = media_names.get(destination, destination)
                relation.attrib.clear()
                relation.set("Id", new_id)
                relation.set("Type", kind)
                relation.set(
                    "Target", posixpath.relpath(destination, posixpath.dirname(source) or ".")
                )
        rels[name] = _serialized(root)
    clean = {}
    for index, name in enumerate(sorted(remaining), 1):
        token.raise_if_cancelled()
        if name in rels:
            clean[name] = rels[name]
        elif name == "[Content_Types].xml":
            # Rebuild this index: source MIME entries and attributes may contain
            # custom data even when their target parts have been removed.
            continue
        elif name.startswith("ppt/media/"):
            data = clean_image_bytes(parts[name])
            with Image.open(io.BytesIO(data)) as image:
                extensions = {
                    "JPEG": {".jpg", ".jpeg"},
                    "PNG": {".png"},
                    "WEBP": {".webp"},
                    "TIFF": {".tif", ".tiff"},
                    "BMP": {".bmp"},
                    "GIF": {".gif"},
                }
                if Path(name).suffix.lower() not in extensions[image.format]:
                    _fail("Embedded image format does not match its filename.")
            clean[media_names[name]] = data
        else:
            root = _xml(parts[name])
            for parent in list(root.iter()):
                for child in list(parent):
                    local = etree.QName(child).localname
                    # Extension bags may hold author/editor IDs or hidden custom data.
                    ids = removed_ids.get(name, set())
                    if local in (
                        "extLst",
                        "custDataLst",
                        "tagLst",
                        "notesMasterIdLst",
                        "custShowLst",
                        "modifyVerifier",
                    ) or any(
                        child.get(f"{{{R}}}{attribute}") in ids
                        for attribute in ("id", "embed", "link")
                    ):
                        parent.remove(child)
            for element in root.iter():
                qualified = etree.QName(element)
                if element.text and element.text.strip() and element.tag != f"{{{A}}}t":
                    _fail("Unsupported hidden XML text outside slide text runs.")
                if qualified.namespace not in (P, A, R, MC):
                    _fail("Unsupported extension XML remains outside an extension bag.")
                for attribute in list(element.attrib):
                    qattr = etree.QName(attribute)
                    if qattr.namespace and qattr.namespace not in (P, A, R, MC, XML):
                        del element.attrib[attribute]
                    elif qattr.localname in (
                        "descr",
                        "title",
                        "tooltip",
                        "author",
                        "userId",
                        "userName",
                    ):
                        del element.attrib[attribute]
                for attribute in ("id", "embed", "link"):
                    key = f"{{{R}}}{attribute}"
                    if key in element.attrib:
                        old_id = element.get(key)
                        if old_id not in retained_ids.get(name, {}):
                            _fail("A slide contains an unresolved relationship reference.")
                        element.set(key, retained_ids[name][old_id])
                element.attrib.pop("matchingName", None)
                if qualified.localname == "fld" and "id" in element.attrib:
                    element.set("id", "{" + str(uuid4()).upper() + "}")
                if qualified.localname in ("theme", "clrScheme", "fontScheme", "fmtScheme"):
                    element.set("name", "Clean theme")
                if qualified.localname == "cNvPr":
                    element.set("name", f"Object {element.get('id', '0')}")
                elif qualified.localname == "cSld":
                    element.attrib.pop("name", None)
                element.attrib.pop(f"{{{MC}}}Ignorable", None)
            etree.cleanup_namespaces(root)
            clean[name] = _serialized(root)
        progress(Progress(index, len(remaining)))
    root = etree.Element(f"{{{CT}}}Types", nsmap={None: CT})
    for extension, mime in (
        ("rels", "application/vnd.openxmlformats-package.relationships+xml"),
        ("xml", "application/xml"),
    ):
        etree.SubElement(root, f"{{{CT}}}Default", Extension=extension, ContentType=mime)
    image_mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
        "bmp": "image/bmp",
        "gif": "image/gif",
    }
    for extension in sorted({Path(n).suffix[1:] for n in clean if n.startswith("ppt/media/")}):
        etree.SubElement(
            root, f"{{{CT}}}Default", Extension=extension, ContentType=image_mime[extension]
        )
    for name in sorted(clean):
        if not name.endswith(".xml"):
            continue
        if name == "ppt/presentation.xml":
            mime = (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
            )
        elif name == "ppt/tableStyles.xml":
            mime = "application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml"
        elif name.startswith("ppt/theme/"):
            mime = "application/vnd.openxmlformats-officedocument.theme+xml"
        else:
            kind = {
                "slides": "slide",
                "slideMasters": "slideMaster",
                "slideLayouts": "slideLayout",
            }[name.split("/")[1]]
            mime = f"application/vnd.openxmlformats-officedocument.presentationml.{kind}+xml"
        etree.SubElement(root, f"{{{CT}}}Override", PartName="/" + name, ContentType=mime)
    clean["[Content_Types].xml"] = _serialized(root)
    return clean


class PptxMetadataConverter:
    spec = ConverterSpec(
        "metadata.clean_pptx",
        "Clean PowerPoint metadata",
        (FileFormat.PPTX,),
        (FileFormat.PPTX,),
        limitations=(
            "Removes document properties, notes, comments, thumbnails, author records and "
            "supported embedded-image metadata. Notes/comments are deleted "
            "permanently in the new copy.",
            "Visible slide content is kept; this does not anonymize text, "
            "pictures or hidden slides. "
            "Complex, linked, embedded, signed, macro or non-raster payloads are rejected.",
            "Embedded raster images are re-encoded; JPEG quality and ICC "
            "color appearance can change.",
        ),
    )

    def validate_options(self, options):
        if options:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "This tool has no conversion options.")
        return {}

    def validate_input(self, input_path):
        try:
            _read_package(input_path)
            return FileFormat.PPTX
        except (OSError, ValueError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Cannot read the PPTX package.") from exc

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        cancel_token.raise_if_cancelled()
        try:
            parts = _read_package(input_path)
            cleaned = _clean_parts(parts, cancel_token, progress)
            # Reparse the actual output with the application's Office parser before publication.
            name = f"clean-presentation-{uuid4().hex[:12]}.pptx"
            report_name = Path(name).stem + ".report.json"
            with OutputTransaction(Path(output_dir)) as output:
                path = output.staging / name
                with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for part, data in sorted(cleaned.items()):
                        cancel_token.raise_if_cancelled()
                        info = zipfile.ZipInfo(part, date_time=(1980, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        info.create_system = 0
                        archive.writestr(info, data)
                from pptx import Presentation

                presentation = Presentation(path)
                from local_pdf_toolkit.converters.image_metadata import verify_clean_image_bytes

                with zipfile.ZipFile(path) as verified:
                    for entry in verified.infolist():
                        cancel_token.raise_if_cancelled()
                        if (
                            entry.filename.startswith(REMOVED_PREFIXES)
                            or entry.filename in REMOVED_FILES
                        ):
                            _fail("Removed metadata parts remain in output.")
                        if entry.comment or entry.extra or entry.date_time != (1980, 1, 1, 0, 0, 0):
                            _fail("Unexpected ZIP metadata remains in output.")
                        if entry.filename.startswith("ppt/media/"):
                            verify_clean_image_bytes(verified.read(entry))
                report = {
                    "tool": "metadata.clean_pptx",
                    "slides": len(presentation.slides),
                    "policy": "Editable OOXML cleaned; ZIP fields reset; raster images rebuilt.",
                    "policy_categories": [
                        "document properties",
                        "notes",
                        "comments/authors",
                        "thumbnails",
                        "tags",
                        "printer/view settings",
                        "extensions",
                        "embedded image metadata",
                    ],
                    "neutralized": [
                        "ZIP timestamps/comments/extras",
                        "shape/theme labels",
                        "media filenames",
                        "relationship IDs",
                    ],
                    "removed_parts": len(set(parts) - set(cleaned)),
                    "limits": "Visible content, hidden slides/shapes and filesystem data can still "
                    "identify people. JPEG/ICC changes and extension removal may affect "
                    "appearance. This report is not an anonymity certificate.",
                }
                (output.staging / report_name).write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                return output.publish([name, report_name], cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR, "Cannot write cleaned PowerPoint."
            ) from exc
        except (ValueError, KeyError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "Invalid or unsupported PPTX structure."
            ) from exc
