"""On-demand structural details; no extraction, conversion engines or source writes."""

import json
import math
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from local_pdf_toolkit.converters.file_probe import FileProbeConverter
from local_pdf_toolkit.converters.images import FORMATS, open_image
from local_pdf_toolkit.converters.inspector import SUPPORTED
from local_pdf_toolkit.converters.office_pdf import _xml
from local_pdf_toolkit.converters.pdf_images import MAX_PAGES
from local_pdf_toolkit.core.contracts import CancellationToken, ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_PAGE_DETAILS = 200
MAX_FONT_DETAILS = 256
MAX_ATTACHMENTS = 100
MAX_REPORT_BYTES = 64 * 1024


def _report_text(details, limits):
    """Keep the saved report inside the desktop reader's bounded JSON limit."""
    report = {"document_details": details, "limits": limits}
    omitted = {}
    while True:
        text = json.dumps(report, indent=2) + "\n"
        if len(text.encode("utf-8")) <= MAX_REPORT_BYTES:
            return text
        candidates = {
            key: value for key, value in details.items() if isinstance(value, list) and value
        }
        if not candidates:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Document details exceed report limits.")
        key = max(candidates, key=lambda name: len(json.dumps(candidates[name])))
        before = len(details[key])
        details[key] = details[key][: before // 2]
        if not omitted:
            limits.append("Detail lists were shortened to keep this report below 64 KiB.")
        omitted[key] = omitted.get(key, 0) + before - len(details[key])
        details["report_list_omissions"] = omitted


def _pdf_details(path, token, limits):
    import pymupdf

    with pymupdf.open(path) as document:
        if not document.is_pdf or document.is_repaired or not 0 < len(document) <= MAX_PAGES:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "The PDF is damaged, empty or too large."
            )
        metadata = document.metadata or {}
        locked = bool(document.needs_pass)
        details = {
            "page_count": len(document),
            "encrypted": locked or bool(metadata.get("encryption")),
            "password_required": locked,
            "encryption": metadata.get("encryption") or ("Password required" if locked else "None"),
        }
        if locked:
            limits.append(
                "The PDF is locked. Fonts, page dimensions and attachments were not read."
            )
            return details
        pages, fonts = [], {}
        for index in range(min(len(document), MAX_PAGE_DETAILS)):
            token.raise_if_cancelled()
            page = document[index]
            pages.append(
                {
                    "page": index + 1,
                    "width_pt": page.rect.width,
                    "height_pt": page.rect.height,
                    "rotation_degrees": page.rotation,
                }
            )
            for _, extension, kind, name, *_ in page.get_fonts():
                key = (name, kind, extension)
                if key not in fonts and len(fonts) < MAX_FONT_DETAILS:
                    fonts[key] = {
                        "name": name[:256],
                        "type": kind[:64],
                        "embedded": extension not in ("", "n/a"),
                    }
        count = document.embfile_count()
        attachments = []
        for index in range(min(count, MAX_ATTACHMENTS)):
            token.raise_if_cancelled()
            info = document.embfile_info(index)
            attachments.append({"name": str(info.get("name", ""))[:256], "bytes": info.get("size")})
        details.update(
            pages=pages, fonts=list(fonts.values()), attachment_count=count, attachments=attachments
        )
        if len(document) > MAX_PAGE_DETAILS:
            limits.append(
                f"Page dimensions and font scanning cover the first {MAX_PAGE_DETAILS} pages."
            )
        if len(fonts) == MAX_FONT_DETAILS:
            limits.append(f"The font list is limited to {MAX_FONT_DETAILS} distinct fonts.")
        if count > MAX_ATTACHMENTS:
            limits.append(f"Only the first {MAX_ATTACHMENTS} attachment names are listed.")
        limits.append("Attachment contents are never extracted. Font names are PDF resource names.")
        return details


def _office_details(path, kind, token, limits):
    # FileProbe has already applied the existing bounded Office package validator.
    with zipfile.ZipFile(path) as package:
        entries = package.infolist()
        token.raise_if_cancelled()
        details = {
            "package_parts": len(entries),
            "uncompressed_bytes": sum(entry.file_size for entry in entries),
        }
        main, tags = {
            "docx": ("word/document.xml", {"paragraph_count": "p", "table_count": "tbl"}),
            "xlsx": ("xl/workbook.xml", {"sheet_count": "sheet"}),
            "pptx": ("ppt/presentation.xml", {"slide_count": "sldId"}),
            "odt": ("content.xml", {"paragraph_count": "p"}),
            "ods": ("content.xml", {"sheet_count": "table"}),
            "odp": ("content.xml", {"slide_count": "page"}),
        }[kind]
        root = _xml(package.read(main))
        counts = dict.fromkeys(tags, 0)
        for index, node in enumerate(root.iter()):
            if index % 1000 == 0:
                token.raise_if_cancelled()
            local = node.tag.rsplit("}", 1)[-1]
            for key, tag in tags.items():
                if local == tag:
                    counts[key] += 1
        details.update(counts)
    limits.append(
        "Office counts describe document structure. Rendered page sizes and fonts require layout."
    )
    return details


class DocumentDetailsConverter:
    spec = ConverterSpec(
        "document.details",
        "Document details",
        SUPPORTED,
        (FileFormat.JSON,),
        limitations=(
            "Creates a structural report. Font and attachment names may contain personal text.",
        ),
    )

    def validate_options(self, options):
        if options:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Document details has no options.")
        return {}

    def validate_input(self, input_path):
        details, _ = self._inspect(Path(input_path), CancellationToken())
        return FileFormat(details["format"])

    def _inspect(self, source, token):
        token.raise_if_cancelled()
        limits = []
        with tempfile.TemporaryDirectory(prefix="pdf-toolkit-details-") as folder:
            temporary = Path(folder)
            try:
                basic = FileProbeConverter()._inspect(source, temporary, token)
            except ConversionError as error:
                if error.code != ErrorCode.PASSWORD_REQUIRED:
                    raise
                basic = {"format": "pdf", "bytes": (temporary / "source.bin").stat().st_size}
            token.raise_if_cancelled()
            kind = basic["format"]
            if FileFormat(kind) not in SUPPORTED:
                raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, "Unsupported document format.")
            snapshot = next(temporary.iterdir())
            details = {"format": kind, "source_bytes": basic["bytes"]}
            if kind == "pdf":
                details.update(_pdf_details(snapshot, token, limits))
            elif kind in {format.value for format in FORMATS.values()}:
                with open_image(snapshot) as image:
                    details.update(width_px=image.width, height_px=image.height, mode=image.mode)
                    dpi = image.info.get("dpi")
                    if isinstance(dpi, tuple | list) and len(dpi) == 2:
                        if all(
                            isinstance(value, int | float) and math.isfinite(value) and value > 0
                            for value in dpi
                        ):
                            details["dpi"] = [round(float(value), 3) for value in dpi]
                limits.append(
                    "Image dimensions follow display orientation; DPI is metadata when present."
                )
            elif kind in ("docx", "xlsx", "pptx", "odt", "ods", "odp"):
                details.update(_office_details(snapshot, kind, token, limits))
            else:
                limits.append("Only verified format and file size are reported for this file type.")
            return details, limits

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        try:
            details, limits = self._inspect(Path(input_path), cancel_token)
            cancel_token.raise_if_cancelled()
            name = f"details-{uuid4().hex[:12]}.report.json"
            with OutputTransaction(Path(output_dir)) as output:
                (output.staging / name).write_text(
                    _report_text(details, limits), encoding="utf-8", newline="\n"
                )
                paths = output.publish([name], cancel_token)
            progress(Progress(1, 1))
            return paths
        except ConversionError:
            raise
        except FileExistsError as error:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR, "The details report already exists."
            ) from error
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "Cannot read this document's details."
            ) from error
