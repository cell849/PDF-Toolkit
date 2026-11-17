"""Bounded, corresponding-page PDF visual and extracted-text comparison."""

import difflib
import io
import math
from contextlib import ExitStack
from pathlib import Path

from PIL import Image, ImageChops

from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.converters.pdf_tools import _safe_stem
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_COMPARE_PAGES = 200
MAX_EDGE = 1400
MAX_TOTAL_PIXELS = 120_000_000
MAX_TEXT_CHARS = 32_000
MAX_TEXT_LINES = 400
MAX_DIFF_LINES = 100


def difference_mask(before, after, threshold):
    """Compare RGB pixels; deltas equal to the threshold are tolerated."""
    delta = ImageChops.difference(before, after)
    red, green, blue = delta.split()
    strongest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return strongest.point(lambda value: 255 if value > threshold else 0)


def _text(page):
    if page is None:
        return [], False
    text = page.get_text(sort=True)
    lines = text[:MAX_TEXT_CHARS].splitlines()
    limited = len(text) > MAX_TEXT_CHARS or len(lines) > MAX_TEXT_LINES
    return [line[:200] for line in lines[:MAX_TEXT_LINES]], (
        limited or any(len(line) > 200 for line in lines[:MAX_TEXT_LINES])
    )


class PdfComparisonConverter:
    spec = ConverterSpec(
        "pdf.compare",
        "Compare two PDFs",
        (FileFormat.PDF,),
        (FileFormat.PDF, FileFormat.TXT),
        (
            OptionDefinition(
                "threshold",
                "Pixel tolerance",
                16,
                "Ignore RGB channel differences up to this value (0–255).",
                minimum=0,
                maximum=255,
            ),
            OptionDefinition(
                "dpi",
                "Comparison DPI",
                96,
                "36–144 DPI, further reduced to 1400 pixels per side.",
                minimum=36,
                maximum=144,
            ),
        ),
        (
            "Compares corresponding page numbers, without page alignment or semantic guarantees.",
            "Visual comparison is rasterized and may miss details below its resolution/tolerance.",
            "Extracted text only; no OCR or layout reconstruction. Text excerpts are bounded.",
            "At most 200 pages and 120 million combined rendered pixels; larger jobs are rejected.",
        ),
        input_mode="multiple",
    )

    def _inputs(self, value):
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not all(isinstance(path, str | Path) for path in value)
        ):
            raise ConversionError(ErrorCode.INVALID_INPUT, "Choose exactly two ordered PDF files.")
        return tuple(Path(path) for path in value)

    def validate_input(self, input_path):
        for path in self._inputs(input_path):
            with PdfImagesConverter(FileFormat.PNG)._open(path) as document:
                if len(document) > MAX_COMPARE_PAGES:
                    raise ConversionError(
                        ErrorCode.INVALID_INPUT, "PDF comparison supports at most 200 pages."
                    )
        return FileFormat.PDF

    def validate_options(self, options):
        if set(options) - {"threshold", "dpi"}:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown comparison option.")
        values = {}
        for definition in self.spec.options:
            value = options.get(definition.name, definition.default)
            if type(value) is not int or not definition.minimum <= value <= definition.maximum:
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS,
                    f"{definition.label} must be {definition.minimum}–{definition.maximum}.",
                )
            values[definition.name] = value
        return values

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        import pymupdf

        paths = self._inputs(input_path)
        values = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        try:
            with ExitStack() as stack:
                sources = [
                    stack.enter_context(PdfImagesConverter(FileFormat.PNG)._open(path))
                    for path in paths
                ]
                count = max(map(len, sources))
                if count > MAX_COMPARE_PAGES:
                    raise ConversionError(
                        ErrorCode.INVALID_INPUT, "PDF comparison supports at most 200 pages."
                    )
                report = stack.enter_context(pymupdf.open())
                report.new_page(width=842, height=595)
                rows, details = [], []
                total_pixels = 0
                progress(Progress(0, count))
                for index in range(count):
                    cancel_token.raise_if_cancelled()
                    pages = [source[index] if index < len(source) else None for source in sources]
                    width = max(page.rect.width for page in pages if page is not None)
                    height = max(page.rect.height for page in pages if page is not None)
                    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                        raise ConversionError(
                            ErrorCode.INVALID_INPUT, "Invalid PDF page dimensions."
                        )
                    scale = min(values["dpi"] / 72, MAX_EDGE / max(width, height))
                    size = (math.ceil(width * scale), math.ceil(height * scale))
                    total_pixels += size[0] * size[1] * 2
                    if total_pixels > MAX_TOTAL_PIXELS:
                        raise ConversionError(
                            ErrorCode.INVALID_INPUT,
                            "Comparison exceeds 120 million rendered pixels. Try a lower DPI.",
                        )
                    images = []
                    for page in pages:
                        cancel_token.raise_if_cancelled()
                        image = Image.new("RGB", size, "white")
                        if page is not None:
                            raster = page.get_pixmap(
                                matrix=pymupdf.Matrix(scale, scale),
                                colorspace=pymupdf.csRGB,
                                alpha=False,
                            )
                            with Image.frombytes(
                                "RGB", (raster.width, raster.height), raster.samples
                            ) as rendered:
                                image.paste(rendered, (0, 0))
                            del raster
                        images.append(image)
                    try:
                        cancel_token.raise_if_cancelled()
                        with difference_mask(*images, values["threshold"]) as mask:
                            pixels = mask.histogram()[255]
                            missing = pages[0] is None or pages[1] is None
                            resized = not missing and pages[0].rect != pages[1].rect
                            first, first_limited = _text(pages[0])
                            cancel_token.raise_if_cancelled()
                            second, second_limited = _text(pages[1])
                            text_changed = first != second
                            changed = pixels > 0 or missing or resized or text_changed
                            status = (
                                "missing from first"
                                if pages[0] is None
                                else "missing from second"
                                if pages[1] is None
                                else "changed"
                                if changed
                                else "no differences detected"
                            )
                            limited = first_limited or second_limited
                            row = (
                                f"Page {index + 1}: {status}; {pixels:,} differing pixels"
                                + ("; page size changed" if resized else "")
                                + ("; extracted text changed" if text_changed else "")
                                + (
                                    "; text comparison incomplete (excerpt limit)"
                                    if limited
                                    else ""
                                )
                            )
                            rows.append(row)
                            details.append(row)
                            if text_changed:
                                diff = list(
                                    difflib.unified_diff(
                                        first,
                                        second,
                                        fromfile="First PDF",
                                        tofile="Second PDF",
                                        lineterm="",
                                        n=2,
                                    )
                                )
                                details.extend(diff[:MAX_DIFF_LINES])
                                if len(diff) > MAX_DIFF_LINES:
                                    details.append(
                                        "[Text diff truncated to 100 lines on this page.]"
                                    )
                            if limited:
                                details.append(
                                    "[Text limited to 32,000 characters, 400 lines and 200 "
                                    "characters per line; unreported text may differ.]"
                                )
                            if changed:
                                self._visual_page(report, images, mask, pages, row, scale)
                    finally:
                        for image in images:
                            image.close()
                    progress(Progress(index + 1, count))
                cancel_token.raise_if_cancelled()
                introduction = [
                    "PDF comparison: corresponding page numbers",
                    f"First: {paths[0].name}",
                    f"Second: {paths[1].name}",
                    f"Pages: {len(sources[0])} / {len(sources[1])}. "
                    f"Requested DPI: {values['dpi']}; pixel tolerance: {values['threshold']}.",
                    "Magenta highlights differing raster pixels; "
                    "page pairs share a top-left origin.",
                    "Changed page pairs follow this summary; "
                    "complete page list is in the text report.",
                    "No page alignment, OCR, semantic comparison or layout guarantees. "
                    "Rendering is capped at 1400 pixels per side.",
                    "No differences detected means only within these rendering and text limits.",
                ]
                # Keep this overview compact even when every detailed row has multiple flags.
                overview = [row.split(";", 1)[0] for row in rows[:20]]
                report[0].insert_textbox(
                    pymupdf.Rect(30, 30, 812, 565),
                    "\n".join(
                        introduction
                        + [""]
                        + overview
                        + (["See text report for remaining pages."] if len(rows) > 20 else [])
                    ),
                    fontsize=10,
                )
                with OutputTransaction(Path(output_dir)) as output:
                    stem = _safe_stem(paths[0]) + "_comparison"
                    names = [stem + ".pdf", stem + ".txt"]
                    report.save(output.staging / names[0], deflate=True, garbage=3)
                    (output.staging / names[1]).write_text(
                        "\n".join(introduction + [""] + details) + "\n", encoding="utf-8"
                    )
                    return output.publish(names, cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "Cannot write comparison. Check output folder and filenames.",
            ) from exc
        except (RuntimeError, ValueError, OverflowError) as exc:
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "PDF comparison failed.") from exc

    @staticmethod
    def _visual_page(report, images, mask, pages, row, scale):
        import pymupdf

        result = report.new_page(width=842, height=595)
        result.insert_textbox(pymupdf.Rect(20, 15, 822, 55), row, fontsize=10)
        for side, image in enumerate(images):
            left = 20 + side * 411
            page = pages[side]
            label = ("First PDF" if side == 0 else "Second PDF") + (
                " - MISSING PAGE"
                if page is None
                else f" - {page.rect.width:g} x {page.rect.height:g} pt"
            )
            result.insert_text((left, 72), label, fontsize=10)
            if page is not None:
                with Image.composite(
                    Image.new("RGB", image.size, "#ff00aa"), image, mask
                ) as marked:
                    stream = io.BytesIO()
                    marked.save(stream, format="PNG")
                    result.insert_image(
                        pymupdf.Rect(left, 85, left + 391, 565), stream=stream.getvalue()
                    )
        result.insert_text(
            (20, 585),
            f"Rendered at {scale * 72:.1f} DPI. "
            "Magenta marks differing pixels; text report lists extraction changes.",
            fontsize=8,
        )
