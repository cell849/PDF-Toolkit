"""Manual redaction by masking rendered pixels and rebuilding every PDF page."""

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pymupdf

from local_pdf_toolkit.converters.pdf_images import MAX_INPUT_BYTES, MAX_PIXELS, PdfImagesConverter
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_REGIONS = 1_000
MAX_REGIONS_BYTES = 128 * 1024
MASK_PADDING_PIXELS = 2
SNAPSHOT_CHUNK_BYTES = 1024 * 1024


@contextmanager
def _snapshot(input_path, expected_sha256, cancel_token):
    """Bind marks to the bytes reviewed, then render only that bounded private copy."""
    with tempfile.TemporaryDirectory(prefix="pdf-toolkit-redaction-") as directory:
        snapshot = Path(directory) / "source.pdf"
        digest = hashlib.sha256()
        total = 0
        try:
            path = Path(input_path)
            if not path.is_file():
                raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a regular PDF file.")
            with path.open("rb") as source, snapshot.open("xb") as target:
                source_stat = os.fstat(source.fileno())
                if not stat.S_ISREG(source_stat.st_mode):
                    raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a regular PDF file.")
                if source_stat.st_size > MAX_INPUT_BYTES:
                    raise ConversionError(ErrorCode.INVALID_INPUT, "PDF exceeds the 512 MiB limit.")
                while True:
                    cancel_token.raise_if_cancelled()
                    chunk = source.read(SNAPSHOT_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_INPUT_BYTES:
                        raise ConversionError(
                            ErrorCode.INVALID_INPUT, "PDF exceeds the 512 MiB limit."
                        )
                    target.write(chunk)
                    digest.update(chunk)
                    cancel_token.raise_if_cancelled()
        except OSError as exc:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "Cannot read or snapshot the PDF source."
            ) from exc
        if expected_sha256 and digest.hexdigest() != expected_sha256:
            raise ConversionError(
                ErrorCode.INVALID_INPUT,
                "The PDF changed after preview. Reopen the preview and mark it again.",
            )
        cancel_token.raise_if_cancelled()
        yield snapshot


def _regions(text):
    """Validate bounded display-space rectangles without retaining source content."""
    if type(text) is not str or len(text) > MAX_REGIONS_BYTES:
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Redaction marks must be bounded JSON.")
    try:
        if len(text.encode("utf-8")) > MAX_REGIONS_BYTES:
            raise ValueError
        values = json.loads(text)
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise ConversionError(
            ErrorCode.INVALID_OPTIONS, "Redaction marks must be valid JSON."
        ) from exc
    if type(values) is not list or not 1 <= len(values) <= MAX_REGIONS:
        raise ConversionError(
            ErrorCode.INVALID_OPTIONS, "Mark at least one area, with at most 1,000 marks."
        )
    required = {"page", "x0", "y0", "x1", "y1"}
    for region in values:
        if (
            type(region) is not dict
            or set(region) != required
            or type(region["page"]) is not int
            or region["page"] < 1
        ):
            raise ConversionError(
                ErrorCode.INVALID_OPTIONS, "Invalid redaction mark or page number."
            )
        coordinates = [region[key] for key in ("x0", "y0", "x1", "y1")]
        if any(
            type(value) not in (int, float) or not 0 <= value <= 1 for value in coordinates
        ) or not (region["x0"] < region["x1"] and region["y0"] < region["y1"]):
            raise ConversionError(
                ErrorCode.INVALID_OPTIONS,
                "Redaction marks need nonempty, finite normalized bounds between 0 and 1.",
            )
    return values


def _verify(path, source, cancel_token):
    """Fail closed if the rebuilt PDF contains original nonvisual data structures."""
    with pymupdf.open(path) as document:
        if (
            len(document) != len(source)
            or document.embfile_count()
            or document.get_xml_metadata()
            or document.xref_get_key(-1, "Info")[0] != "null"
            or document.xref_get_key(-1, "ID")[0] != "null"
            or any(
                value
                for key, value in document.metadata.items()
                if key not in ("format", "encryption")
            )
        ):
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "Redaction verification failed.")
        for index, page in enumerate(document):
            cancel_token.raise_if_cancelled()
            if (
                page.rect != source[index].rect
                or page.get_text()
                or next(page.annots(), None) is not None
                or next(page.widgets(), None) is not None
                or page.get_links()
            ):
                raise ConversionError(ErrorCode.CONVERSION_FAILED, "Redaction verification failed.")


class PdfRedactionConverter:
    spec = ConverterSpec(
        "pdf.redact",
        "Redact marked PDF areas",
        (FileFormat.PDF,),
        (FileFormat.PDF,),
        (
            OptionDefinition(
                "regions",
                "Redaction marks",
                "[]",
                "JSON list of page numbers (starting at 1) and normalized x0, y0, x1, y1 "
                "bounds on the displayed page, including its rotation and crop.",
            ),
            OptionDefinition(
                "dpi", "Page resolution (DPI)", 150, "Raster resolution.", (72, 150, 300)
            ),
            OptionDefinition(
                "source_sha256",
                "Reviewed source SHA-256",
                "",
                "Internal binding to reviewed source bytes; empty for unbound CLI use.",
            ),
        ),
        (
            "Permanently masks marked pixels with black and rebuilds every page as an image. "
            "All selectable text and interactivity are lost; "
            "visible content outside marks remains.",
            "Originals are preserved. Review every page and mark all sensitive visible content. "
            "This is manual redaction, not automatic sensitive-content detection.",
        ),
    )

    def validate_input(self, input_path):
        return PdfImagesConverter(FileFormat.PNG).validate_input(input_path)

    def validate_options(self, options):
        dpi = options.get("dpi", 150)
        if (
            set(options) - {"dpi", "regions", "source_sha256"}
            or type(dpi) is not int
            or dpi not in (72, 150, 300)
        ):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Choose 72, 150 or 300 DPI.")
        source_sha256 = options.get("source_sha256", "")
        if type(source_sha256) is not str or (
            source_sha256 and re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None
        ):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid reviewed source SHA-256.")
        regions = options.get("regions", "[]")
        _regions(regions)
        return {"dpi": dpi, "regions": regions, "source_sha256": source_sha256}

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        options = self.validate_options(options)
        regions = _regions(options["regions"])
        dpi = options["dpi"]
        cancel_token.raise_if_cancelled()
        name = f"redacted-document-{uuid4().hex[:12]}.pdf"
        report_name = Path(name).stem + ".report.json"
        try:
            with (
                _snapshot(input_path, options["source_sha256"], cancel_token) as snapshot,
                PdfImagesConverter(FileFormat.PNG)._open(snapshot) as source,
                pymupdf.open() as redacted,
                OutputTransaction(Path(output_dir)) as output,
            ):
                if any(region["page"] > len(source) for region in regions):
                    raise ConversionError(
                        ErrorCode.INVALID_OPTIONS,
                        f"Redaction pages must be within 1–{len(source)}.",
                    )
                marks = {}
                for region in regions:
                    marks.setdefault(region["page"], []).append(region)
                progress(Progress(0, len(source)))
                for index, page in enumerate(source, 1):
                    cancel_token.raise_if_cancelled()
                    if (
                        math.ceil(page.rect.width * dpi / 72)
                        * math.ceil(page.rect.height * dpi / 72)
                        > MAX_PIXELS
                    ):
                        raise ConversionError(
                            ErrorCode.INVALID_INPUT,
                            "Page exceeds 40 million pixels. Choose a lower DPI.",
                        )
                    pixels = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
                    cancel_token.raise_if_cancelled()
                    for region in marks.get(index, ()):
                        cancel_token.raise_if_cancelled()
                        # Raster coordinates are already in displayed rotation/crop space.
                        # Round outward and pad to cover antialiased boundary pixels.
                        bounds = pymupdf.IRect(
                            max(0, math.floor(region["x0"] * pixels.width) - MASK_PADDING_PIXELS),
                            max(0, math.floor(region["y0"] * pixels.height) - MASK_PADDING_PIXELS),
                            min(
                                pixels.width,
                                math.ceil(region["x1"] * pixels.width) + MASK_PADDING_PIXELS,
                            ),
                            min(
                                pixels.height,
                                math.ceil(region["y1"] * pixels.height) + MASK_PADDING_PIXELS,
                            ),
                        )
                        pixels.set_rect(bounds, (0, 0, 0))
                    target = redacted.new_page(width=page.rect.width, height=page.rect.height)
                    target.insert_image(target.rect, stream=pixels.tobytes("png"))
                    del pixels
                    progress(Progress(index, len(source)))
                cancel_token.raise_if_cancelled()
                redacted.save(output.staging / name, garbage=4, deflate=True, no_new_id=True)
                cancel_token.raise_if_cancelled()
                _verify(output.staging / name, source, cancel_token)
                report = {
                    "tool": self.spec.operation_id,
                    "pages": len(source),
                    "marked_pages": len(marks),
                    "masked_regions": len(regions),
                    "dpi": dpi,
                    "policy": "Marked rendered pixels replaced by opaque black with outward "
                    "padding; every page rebuilt from PNG pixels in a fresh PDF. "
                    "No source PDF objects copied. Originals are untouched.",
                    "removed": "All selectable text, attachments, document metadata, scripts, "
                    "forms, links, and interactive annotations.",
                    "limits": "All selectable text and interactivity are lost. Visual content "
                    "outside the marked areas and their small safety padding is retained. "
                    "Only manually marked visible content is masked. Review every page. "
                    "Filesystem metadata and pixel steganography are outside this policy.",
                }
                (output.staging / report_name).write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                return output.publish([name, report_name], cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR, "Cannot save redacted outputs; check permissions and space."
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "Cannot render or verify this PDF for redaction."
            ) from exc


def redaction_converters():
    return (PdfRedactionConverter(),)
