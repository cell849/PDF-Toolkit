"""Explicitly lossy PDF exports: text DOCX, detected-table XLSX, rendered PPTX."""

import importlib
import io
import math
import re
from pathlib import Path

from local_pdf_toolkit.converters.pdf_images import MAX_PIXELS, PdfImagesConverter, page_selection
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

_LIBRARIES = {"docx": "docx", "xlsx": "openpyxl", "pptx": "pptx"}
_LIMITATIONS = {
    "docx": "Reconstructs selectable text as paragraphs; "
    "layout, images and tables are not preserved. "
    "Scanned pages need OCR, which is not included.",
    "xlsx": "Exports tables detected by PyMuPDF only. Detection may miss tables; "
    "scanned tables need OCR, which is not included.",
    "pptx": "Each PDF page becomes one image slide. Slide contents are not editable; "
    "mixed page sizes are fitted within the first selected page's slide size.",
}


def _dependency(kind):
    try:
        return importlib.import_module(_LIBRARIES[kind])
    except ImportError as exc:
        package = {"docx": "python-docx", "xlsx": "openpyxl", "pptx": "python-pptx"}[kind]
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED, f"This export requires the {package} package."
        ) from exc


class PdfOfficeConverter:
    def __init__(self, output_format):
        if output_format.value not in _LIBRARIES:
            raise ValueError("Unsupported PDF Office export.")
        self.output_format = output_format
        options = [OptionDefinition("pages", "Pages", "all", "All pages or a range such as 1,3-5.")]
        if output_format == FileFormat.PPTX:
            options.append(
                OptionDefinition(
                    "dpi", "Resolution (DPI)", 150, "Rendered slide resolution.", (72, 150, 300)
                )
            )
        self.spec = ConverterSpec(
            f"pdf.to_{output_format.value}",
            f"PDF to {output_format.value.upper()}",
            (FileFormat.PDF,),
            (output_format,),
            tuple(options),
            (_LIMITATIONS[output_format.value], "No OCR, AI or cloud processing is used."),
        )
        self._pdf = PdfImagesConverter(FileFormat.PNG)

    def validate_input(self, input_path):
        return self._pdf.validate_input(input_path)

    def validate_options(self, options):
        definitions = {definition.name: definition for definition in self.spec.options}
        if set(options) - definitions.keys():
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown conversion option.")
        values = {
            name: options.get(name, definition.default) for name, definition in definitions.items()
        }
        for name, value in values.items():
            definition = definitions[name]
            if type(value) is not type(definition.default) or (
                definition.choices and value not in definition.choices
            ):
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {definition.label}.")
        if len(values["pages"]) > 4096:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Page range is too long.")
        return values

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        options = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        module = _dependency(self.output_format.value)
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(input_path).stem).rstrip(" .")[:100]
        name = f"{stem or 'document'}.{self.output_format.value}"
        try:
            with self._pdf._open(Path(input_path)) as document:
                pages = page_selection(options["pages"], len(document))
                with OutputTransaction(Path(output_dir)) as outputs:
                    if (outputs.directory / name).exists():
                        raise ConversionError(ErrorCode.OUTPUT_ERROR, "Output already exists.")
                    progress(Progress(0, len(pages)))
                    target = outputs.staging / name
                    if self.output_format == FileFormat.DOCX:
                        self._docx(module, document, pages, target, progress, cancel_token)
                    elif self.output_format == FileFormat.XLSX:
                        self._xlsx(module, document, pages, target, progress, cancel_token)
                    else:
                        self._pptx(module, document, pages, target, options, progress, cancel_token)
                    return outputs.publish([name], cancel_token)
        except OSError as exc:
            raise ConversionError(ErrorCode.OUTPUT_ERROR, "Cannot write Office export.") from exc
        except (RuntimeError, ValueError, TypeError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"PDF Office export failed: {exc}"
            ) from exc

    @staticmethod
    def _docx(module, document, pages, target, progress, cancel_token):
        output = module.Document()
        found_text = False
        for completed, index in enumerate(pages, 1):
            cancel_token.raise_if_cancelled()
            if completed > 1:
                output.add_page_break()
            text = document[index].get_text("text", sort=True)
            if text.strip():
                found_text = True
                for paragraph in re.split(r"\n\s*\n", text.strip()):
                    cancel_token.raise_if_cancelled()
                    # XML cannot represent most control characters in document text.
                    paragraph = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", paragraph)
                    output.add_paragraph(paragraph)
            progress(Progress(completed, len(pages)))
        if not found_text:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "No selectable text found. Scanned PDFs require OCR."
            )
        cancel_token.raise_if_cancelled()
        output.save(target)

    @staticmethod
    def _xlsx(module, document, pages, target, progress, cancel_token):
        output = module.Workbook()
        output.remove(output.active)
        count = 0
        try:
            for completed, index in enumerate(pages, 1):
                cancel_token.raise_if_cancelled()
                page = document[index]
                finder = page.find_tables()
                for table_index, table in enumerate(finder.tables, 1):
                    cancel_token.raise_if_cancelled()
                    rows = table.extract()
                    if not rows or not any(any(cell for cell in row) for row in rows):
                        continue
                    sheet = output.create_sheet(f"Page {index + 1} Table {table_index}"[:31])
                    for row_index, row in enumerate(rows, 1):
                        cancel_token.raise_if_cancelled()
                        if row_index > 1048576 or len(row) > 16384:
                            raise ConversionError(
                                ErrorCode.INVALID_INPUT, "Detected table exceeds Excel limits."
                            )
                        for column, value in enumerate(row, 1):
                            if value is not None:
                                value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
                                if len(value) > 32767:
                                    raise ConversionError(
                                        ErrorCode.INVALID_INPUT,
                                        "Detected table cell exceeds Excel's text length limit.",
                                    )
                                # PDF text beginning '=' must never become a formula.
                                cell = sheet.cell(row_index, column, value)
                                cell.data_type = "s"
                    sheet.freeze_panes = "A2"
                    count += 1
                progress(Progress(completed, len(pages)))
            if not count:
                raise ConversionError(
                    ErrorCode.INVALID_INPUT,
                    "No tables detected in the selected pages. No workbook created.",
                )
            cancel_token.raise_if_cancelled()
            output.save(target)
        finally:
            output.close()

    @staticmethod
    def _pptx(module, document, pages, target, options, progress, cancel_token):
        import pymupdf

        output = module.Presentation()
        first = document[pages[0]].rect
        # OOXML presentation dimensions are limited to 1–56 inches. Scale unusually
        # small/large PDF pages without changing their aspect ratio.
        factor = min(1.0, 56 * 72 / max(first.width, first.height))
        factor = max(factor, 72 / min(first.width, first.height))
        width, height = first.width * factor, first.height * factor
        if max(width, height) > 56 * 72:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "PDF aspect ratio is too extreme for PPTX."
            )
        output.slide_width = round(width * 12700)
        output.slide_height = round(height * 12700)
        for completed, index in enumerate(pages, 1):
            cancel_token.raise_if_cancelled()
            page = document[index]
            scale = options["dpi"] / 72
            if (
                math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale)
                > MAX_PIXELS
            ):
                raise ConversionError(
                    ErrorCode.INVALID_INPUT, "Page exceeds 40 million pixels. Try a lower DPI."
                )
            pixmap = page.get_pixmap(dpi=options["dpi"], colorspace=pymupdf.csRGB, alpha=False)
            cancel_token.raise_if_cancelled()
            slide = output.slides.add_slide(output.slide_layouts[6])
            fit = min(output.slide_width / pixmap.width, output.slide_height / pixmap.height)
            image_width, image_height = round(pixmap.width * fit), round(pixmap.height * fit)
            slide.shapes.add_picture(
                io.BytesIO(pixmap.tobytes("png")),
                (output.slide_width - image_width) // 2,
                (output.slide_height - image_height) // 2,
                width=image_width,
                height=image_height,
            )
            del pixmap
            progress(Progress(completed, len(pages)))
        cancel_token.raise_if_cancelled()
        output.save(target)


def pdf_office_converters():
    return tuple(PdfOfficeConverter(FileFormat(kind)) for kind in _LIBRARIES)
