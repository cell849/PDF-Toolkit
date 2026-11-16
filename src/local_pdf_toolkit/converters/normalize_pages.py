"""Normalize selected PDF sheets while preserving vector and selectable text content."""

import math
from pathlib import Path

import pymupdf

from local_pdf_toolkit.converters.pdf_images import MAX_PIXELS, PdfImagesConverter, page_selection
from local_pdf_toolkit.converters.pdf_tools import _safe_stem
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

POINTS_PER_MM = 72 / 25.4
MIN_PAGE_POINTS = 10
MAX_PAGE_POINTS = 14_400
MAX_MARGIN_MM = 100
UNIT_POINTS = {"mm": POINTS_PER_MM, "cm": 10 * POINTS_PER_MM, "in": 72, "pt": 1}

# Published ISO 216 / ISO 269 dimensions in millimetres, including rounded small sizes.
PAPER_SIZES_MM = {
    **dict(
        zip(
            (f"A{i}" for i in range(11)),
            (
                (841, 1189),
                (594, 841),
                (420, 594),
                (297, 420),
                (210, 297),
                (148, 210),
                (105, 148),
                (74, 105),
                (52, 74),
                (37, 52),
                (26, 37),
            ),
            strict=True,
        )
    ),
    **dict(
        zip(
            (f"B{i}" for i in range(11)),
            (
                (1000, 1414),
                (707, 1000),
                (500, 707),
                (353, 500),
                (250, 353),
                (176, 250),
                (125, 176),
                (88, 125),
                (62, 88),
                (44, 62),
                (31, 44),
            ),
            strict=True,
        )
    ),
    **dict(
        zip(
            (f"C{i}" for i in range(11)),
            (
                (917, 1297),
                (648, 917),
                (458, 648),
                (324, 458),
                (229, 324),
                (162, 229),
                (114, 162),
                (81, 114),
                (57, 81),
                (40, 57),
                (28, 40),
            ),
            strict=True,
        )
    ),
}
PAPER_SIZES_POINTS = {
    name: (width * POINTS_PER_MM, height * POINTS_PER_MM)
    for name, (width, height) in PAPER_SIZES_MM.items()
} | {"Letter": (612, 792), "Legal": (612, 1008), "Tabloid": (792, 1224)}


def _check_page_size(width, height, code):
    if (
        not all(math.isfinite(value) for value in (width, height))
        or min(width, height) < MIN_PAGE_POINTS
        or max(width, height) > MAX_PAGE_POINTS
        or math.ceil(width) * math.ceil(height) > MAX_PIXELS
    ):
        raise ConversionError(
            code,
            "Page dimensions must be 10–14,400 pt with at most 40 million pixels at 72 DPI.",
        )


class PdfNormalizePagesConverter:
    def __init__(self):
        self.spec = ConverterSpec(
            "pdf.normalize_pages",
            "Normalize PDF page sizes",
            (FileFormat.PDF,),
            (FileFormat.PDF,),
            (
                OptionDefinition("pages", "Pages", "all", "All pages or a range such as 1,3-5."),
                OptionDefinition(
                    "paper",
                    "Paper size",
                    "A4",
                    "Size for selected pages.",
                    (*PAPER_SIZES_POINTS, "custom"),
                ),
                OptionDefinition(
                    "orientation",
                    "Orientation",
                    "auto",
                    "Auto matches each selected page's displayed orientation.",
                    ("portrait", "landscape", "auto"),
                ),
                OptionDefinition(
                    "custom_width",
                    "Custom width",
                    210.0,
                    "Used for custom paper; physical dimensions must be 10–14,400 pt.",
                    minimum=0,
                    maximum=14_400,
                ),
                OptionDefinition(
                    "custom_height",
                    "Custom height",
                    297.0,
                    "Used for custom paper; at most 40 million pixels at 72 DPI.",
                    minimum=0,
                    maximum=14_400,
                ),
                OptionDefinition(
                    "units",
                    "Custom units",
                    "mm",
                    "Units for custom dimensions.",
                    ("mm", "cm", "in", "pt"),
                ),
                OptionDefinition(
                    "fit",
                    "Fit content",
                    "contain",
                    "Contain keeps the whole page; cover crops its edges to fill the area.",
                    ("contain", "cover"),
                ),
                OptionDefinition(
                    "margin_mm",
                    "Margin (mm)",
                    0.0,
                    "Equal margins on every side; must leave a nonempty content area.",
                    minimum=0,
                    maximum=MAX_MARGIN_MM,
                ),
            ),
            (
                "Selected pages keep vector graphics and selectable text; "
                "cover crops visible edges.",
                "Selected-page annotation and form appearances become permanent; links and "
                "interactivity are lost. Unselected pages are copied.",
                "Document bookmarks, attachments, signatures and advanced document features are "
                "not preserved. This is not a redaction tool; "
                "cropped content may remain recoverable.",
            ),
        )

    def _path(self, input_path):
        if not isinstance(input_path, str | Path):
            raise ConversionError(ErrorCode.INVALID_INPUT, "Choose one PDF file.")
        return Path(input_path)

    def _open(self, input_path):
        document = PdfImagesConverter(FileFormat.PNG)._open(self._path(input_path))
        # Owner-only encryption can open without a password, but still has restrictions.
        if document.metadata.get("encryption"):
            document.close()
            raise ConversionError(
                ErrorCode.PASSWORD_REQUIRED, "Unlock the PDF before normalizing it."
            )
        return document

    def validate_input(self, input_path):
        with self._open(input_path):
            return FileFormat.PDF

    def validate_options(self, options):
        definitions = {item.name: item for item in self.spec.options}
        if set(options) - definitions.keys():
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown conversion option.")
        values = {name: options.get(name, item.default) for name, item in definitions.items()}
        for name, item in definitions.items():
            value = values[name]
            if isinstance(item.default, float):
                if type(value) not in (int, float):
                    raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {item.label}.")
                if not item.minimum <= value <= item.maximum:
                    raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {item.label}.")
                if not math.isfinite(value):
                    raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {item.label}.")
            elif type(value) is not str or len(value) > 4096:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {item.label}.")
            if item.choices and value not in item.choices:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Unsupported {item.label}.")
        width, height = self._dimensions(values)
        _check_page_size(width, height, ErrorCode.INVALID_OPTIONS)
        if 2 * values["margin_mm"] * POINTS_PER_MM >= min(width, height):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Margins leave no content area.")
        return values

    def _dimensions(self, values):
        if values["paper"] == "custom":
            scale = UNIT_POINTS[values["units"]]
            return values["custom_width"] * scale, values["custom_height"] * scale
        return PAPER_SIZES_POINTS[values["paper"]]

    def _normalize(self, source, index, result, values):
        source_page = source[index]
        width, height = sorted(self._dimensions(values))
        landscape = values["orientation"] == "landscape" or (
            values["orientation"] == "auto" and source_page.rect.width > source_page.rect.height
        )
        if landscape:
            width, height = height, width
        target = result.new_page(width=width, height=height)
        margin = values["margin_mm"] * POINTS_PER_MM
        inner = pymupdf.Rect(margin, margin, width - margin, height - margin)
        # Bake a single-page copy, so unselected pages keep their annotations and widgets.
        with pymupdf.open() as visible:
            visible.insert_pdf(source, from_page=index, to_page=index)
            visible.bake(annots=True, widgets=True)
            page = visible[0]
            rotation = page.rotation
            clip = pymupdf.Rect(page.rect)
            if values["fit"] == "cover":
                ratio = inner.width / inner.height
                if clip.width / clip.height > ratio:
                    trim = (clip.width - clip.height * ratio) / 2
                    clip.x0 += trim
                    clip.x1 -= trim
                else:
                    trim = (clip.height - clip.width / ratio) / 2
                    clip.y0 += trim
                    clip.y1 -= trim
            # Work in displayed coordinates, then map the clip back before importing.
            # remove_rotation() can shift content on pages with an offset crop box.
            clip = clip * page.derotation_matrix
            page.set_rotation(0)
            if page.get_contents():
                target.show_pdf_page(
                    inner, visible, 0, clip=clip, rotate=-rotation, keep_proportion=True
                )

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        values = self.validate_options(options)
        path = self._path(input_path)
        cancel_token.raise_if_cancelled()
        try:
            with self._open(path) as source, pymupdf.open() as result:
                selected = set(page_selection(values["pages"], len(source)))
                with OutputTransaction(Path(output_dir)) as outputs:
                    progress(Progress(0, len(source)))
                    for index, page in enumerate(source):
                        cancel_token.raise_if_cancelled()
                        _check_page_size(page.rect.width, page.rect.height, ErrorCode.INVALID_INPUT)
                        if index in selected:
                            self._normalize(source, index, result, values)
                        else:
                            result.insert_pdf(source, from_page=index, to_page=index)
                        progress(Progress(index + 1, len(source)))
                    cancel_token.raise_if_cancelled()
                    # Single-page insert_pdf cannot retain destinations outside its page range.
                    # Restore those links only after every destination exists in the result.
                    for index, page in enumerate(source):
                        if index in selected:
                            continue
                        cancel_token.raise_if_cancelled()
                        for link in page.get_links():
                            if (
                                link["kind"] == pymupdf.LINK_GOTO
                                and link.get("page", -1) >= 0
                                and link["page"] != index
                            ):
                                destination = link["page"]
                                point = link.get("to", pymupdf.Point(0, 0))
                                if destination in selected:
                                    before = source[destination].rect
                                    after = result[destination].rect
                                    margin = values["margin_mm"] * POINTS_PER_MM
                                    scales = (
                                        (after.width - 2 * margin) / before.width,
                                        (after.height - 2 * margin) / before.height,
                                    )
                                    scale = (min if values["fit"] == "contain" else max)(scales)
                                    point = pymupdf.Point(
                                        point.x * scale + (after.width - before.width * scale) / 2,
                                        point.y * scale
                                        + (after.height - before.height * scale) / 2,
                                    )
                                else:
                                    point = point * source[destination].derotation_matrix
                                result[index].insert_link(
                                    {
                                        "kind": pymupdf.LINK_GOTO,
                                        "from": link["from"] * page.derotation_matrix,
                                        "page": destination,
                                        "to": point,
                                        "zoom": link.get("zoom", 0),
                                    }
                                )
                    result.set_metadata(source.metadata)
                    name = f"{_safe_stem(path)}_normalized.pdf"
                    result.save(outputs.staging / name, garbage=4, deflate=True, no_new_id=True)
                    cancel_token.raise_if_cancelled()
                    return outputs.publish([name], cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "Cannot save normalized PDF; check existing filenames, permissions and free space.",
            ) from exc
        except (RuntimeError, ValueError, OverflowError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"PDF page normalization failed: {exc}"
            ) from exc


def normalize_page_converters():
    return (PdfNormalizePagesConverter(),)
