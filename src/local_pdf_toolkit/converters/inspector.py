"""Masked metadata inventory and count comparison; no private field values exported."""

import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from lxml import etree
from PIL import ExifTags

from local_pdf_toolkit.converters.image_metadata import _open as open_image_bytes
from local_pdf_toolkit.converters.images import FORMATS
from local_pdf_toolkit.converters.metadata_package import parse_xml_parts, read_package
from local_pdf_toolkit.core.contracts import CancellationToken, ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

SUPPORTED = (
    FileFormat.PDF,
    *FORMATS.values(),
    FileFormat.DOCX,
    FileFormat.XLSX,
    FileFormat.PPTX,
    FileFormat.ODT,
    FileFormat.ODS,
    FileFormat.ODP,
    FileFormat.RTF,
    FileFormat.TXT,
    FileFormat.CSV,
    FileFormat.MARKDOWN,
    *(
        FileFormat(kind)
        for kind in ("mp4", "mov", "mkv", "webm", "avi", "mp3", "m4a", "wav", "flac", "ogg", "aac")
    ),
)


def _inventory(path, token):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= 512 * 1024 * 1024:
        raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a regular file below 512 MiB.")
    token.raise_if_cancelled()
    with path.open("rb") as stream:
        header = stream.read(1024)
    counts = {}

    def add(key, value=1):
        if value:
            counts[key] = counts.get(key, 0) + value

    if header.lstrip().startswith(b"%PDF-"):
        from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter

        with PdfImagesConverter(FileFormat.PNG)._open(path) as doc:
            for key in (
                "title",
                "author",
                "subject",
                "keywords",
                "creator",
                "producer",
                "creationDate",
                "modDate",
            ):
                add("PDF property: " + key, int(bool(doc.metadata.get(key))))
            add("PDF XMP packet", int(bool(doc.get_xml_metadata())))
            add("PDF attachments", doc.embfile_count())
            for page in doc:
                token.raise_if_cancelled()
                add("PDF annotations", len(list(page.annots() or ())))
                add("PDF form fields", len(list(page.widgets() or ())))
                add("PDF links", len(page.get_links()))
        kind = "PDF"
    elif header.startswith(b"PK"):
        parts = read_package(path)
        roots = parse_xml_parts(parts)
        kind = (
            "DOCX"
            if "word/document.xml" in parts
            else "XLSX"
            if "xl/workbook.xml" in parts
            else "PPTX"
            if "ppt/presentation.xml" in parts
            else "OpenDocument"
            if "mimetype" in parts
            else ""
        )
        if kind == "OpenDocument":
            mime = parts.get("mimetype", b"")
            kind = {
                b"application/vnd.oasis.opendocument.text": "ODT",
                b"application/vnd.oasis.opendocument.spreadsheet": "ODS",
                b"application/vnd.oasis.opendocument.presentation": "ODP",
            }.get(mime, "")
        if not kind:
            raise ConversionError(
                ErrorCode.UNSUPPORTED_FORMAT, "This archive is not a supported Office document."
            )
        for name, root in roots.items():
            token.raise_if_cancelled()
            if name.startswith("docProps/") or name == "meta.xml":
                for node in root.iter():
                    if node.text and node.text.strip():
                        # Custom property names and their values are never exported.
                        local = node.tag.rsplit("}", 1)[-1]
                        known = {
                            "creator",
                            "lastModifiedBy",
                            "title",
                            "subject",
                            "description",
                            "keywords",
                            "created",
                            "modified",
                            "Company",
                            "Manager",
                            "generator",
                            "initial-creator",
                            "creation-date",
                            "date",
                            "editing-duration",
                            "editing-cycles",
                        }
                        add(
                            "Office property: " + local
                            if local in known
                            else "Office other properties"
                        )
            else:
                for node in root.iter():
                    local = node.tag.rsplit("}", 1)[-1]
                    if local in ("comment", "annotation", "cm", "person", "commentAuthor"):
                        add("Office comments/reviewer records")
                    if local in ("ins", "del", "moveFrom", "moveTo", "tracked-changes"):
                        add("Office revision records")
            if name.startswith("customXml/"):
                add("Office custom XML parts")
        add(
            "Office notes parts",
            sum(n.startswith("ppt/notesSlides/") and n.endswith(".xml") for n in parts),
        )
        with zipfile.ZipFile(path) as archive:
            add("ZIP comment", int(bool(archive.comment)))
            add(
                "ZIP source timestamps",
                sum(e.date_time != (1980, 1, 1, 0, 0, 0) for e in archive.infolist()),
            )
            add(
                "ZIP entry comments/extras",
                sum(bool(e.comment or e.extra) for e in archive.infolist()),
            )
        for name, data in parts.items():
            token.raise_if_cancelled()
            if "/media/" in name or name.startswith("Pictures/"):
                try:
                    with open_image_bytes(data) as image:
                        add_image_fields(image, add, prefix="Embedded image: ")
                except (ConversionError, OSError, ValueError):
                    add("Embedded media not inspected")
    elif header.startswith(b"{\\rtf"):
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ConversionError(ErrorCode.INVALID_INPUT, "RTF inspection limit is 16 MiB.")
        from local_pdf_toolkit.converters.text_metadata import clean_rtf

        data = path.read_bytes()
        clean_rtf(data)  # Fail honestly on unsupported embedded/active structures.
        for word in (
            "info",
            "userprops",
            "generator",
            "annotation",
            "author",
            "operator",
            "company",
            "manager",
            "rsidtbl",
        ):
            add("RTF " + word + " records", len(re.findall(rb"\\" + word.encode() + rb"\b", data)))
        kind = "RTF"
    elif path.suffix.lower() in (".txt", ".csv", ".md"):
        from local_pdf_toolkit.converters.text_metadata import TextMetadataConverter

        kind = TextMetadataConverter().validate_input(path).value.upper()
        # Frontmatter is not automatically interpreted or declared scrubbed.
        if path.suffix.lower() == ".md" and header.lstrip().startswith((b"---", b"+++")):
            add("Possible Markdown frontmatter (content not inspected)")
    elif path.suffix.lower() in {
        ".mp4",
        ".mov",
        ".mkv",
        ".webm",
        ".avi",
        ".mp3",
        ".m4a",
        ".wav",
        ".flac",
        ".ogg",
        ".aac",
    }:
        from local_pdf_toolkit.converters.media_metadata import inspect_media

        media = inspect_media(path, token)
        kind = media["format"].value.upper()
        counts.update(media["counts"])
    else:
        try:
            with open_image_bytes(path.read_bytes()) as image:
                kind = FORMATS[image.format].value.upper()
                add_image_fields(image, add)
        except (OSError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.UNSUPPORTED_FORMAT, "Cannot inspect this file format."
            ) from exc
    token.raise_if_cancelled()
    return {"format": kind, "counts": counts, "fields_detected": sum(counts.values())}


def inventory(path, token):
    try:
        return _inventory(path, token)
    except ConversionError:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        raise ConversionError(
            ErrorCode.INVALID_INPUT, "This file cannot be parsed for inspection."
        ) from exc


def add_image_fields(image, add, prefix=""):
    exif = image.getexif()
    for tag in exif:
        if image.format == "TIFF" and tag in {
            256,
            257,
            258,
            259,
            262,
            273,
            277,
            278,
            279,
            284,
            338,
            339,
        }:
            continue
        label = ExifTags.TAGS.get(tag, "Unknown EXIF tag")
        add(prefix + "EXIF: " + label)
    known = {
        "exif",
        "xmp",
        "icc_profile",
        "comment",
        "photoshop",
        "XML:com.adobe.xmp",
        "description",
    }
    for key in known:
        if image.info.get(key):
            add(prefix + "image " + key)
    # Do not copy private text chunk keys, which can themselves contain names.
    text_entries = getattr(image, "text", {})
    add(prefix + "PNG text entries", len(text_entries))


class MetadataInspector:
    spec = ConverterSpec(
        "metadata.inspect",
        "Inspect / compare metadata",
        SUPPORTED,
        (FileFormat.JSON,),
        limitations=(
            "Select one file to inspect, or two in order: original first, cleaned copy second. "
            "Reports contain detected field counts and categories, never original field values.",
            "Detection is format-specific, not exhaustive forensic analysis. A zero count "
            "does not prove anonymity; visible/hidden content and unknown metadata may remain.",
        ),
        input_mode="multiple",
    )

    def validate_options(self, options):
        if options:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "This inspector has no options.")
        return {}

    def validate_input(self, path):
        result = inventory(path, CancellationToken())
        return FileFormat(result["format"].lower())

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        paths = (input_path,) if isinstance(input_path, str | Path) else tuple(input_path)
        if not 1 <= len(paths) <= 2:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "Select one file, or original then cleaned file."
            )
        try:
            inspections = []
            for index, path in enumerate(paths, 1):
                inspections.append(inventory(path, cancel_token))
                progress(Progress(index, len(paths)))
            report = {
                "tool": self.spec.operation_id,
                "policy": "Masked, format-aware metadata inventory.",
                "inspection": inspections,
                "limits": "No values or source names are exported. "
                "Counts are not a complete privacy audit. "
                "Zero detected fields does not mean anonymous; personal content can remain.",
            }
            if len(inspections) == 2:
                before, after = (item["counts"] for item in inspections)
                report["comparison"] = [
                    {"category": key, "before": before.get(key, 0), "after": after.get(key, 0)}
                    for key in sorted(before.keys() | after.keys())
                ]
            name = f"inspection-{uuid4().hex[:12]}.report.json"
            with OutputTransaction(Path(output_dir)) as output:
                (output.staging / name).write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                return output.publish([name], cancel_token)
        except (OSError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "Cannot inspect or save this metadata report."
            ) from exc
