"""A strict PDF copy built only from rendered pages, without source PDF objects."""

import json
import math
from pathlib import Path
from uuid import uuid4

import pymupdf

from local_pdf_toolkit.converters.pdf_images import MAX_PIXELS, PdfImagesConverter
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction


class PdfMetadataConverter:
    spec = ConverterSpec(
        "metadata.clean_pdf",
        "Clean PDF metadata (flattened)",
        (FileFormat.PDF,),
        (FileFormat.PDF,),
        (
            OptionDefinition(
                "dpi",
                "Page resolution (DPI)",
                150,
                "Rebuilds pages as images. Use 72 DPI for unusually large pages.",
                (72, 150, 300),
            ),
        ),
        (
            "Rebuilds every page as an image in a new PDF. Source properties, attachments, "
            "scripts, hidden text, forms, links and annotations as "
            "interactive objects are omitted.",
            "Removes selectable text and vector/editable structure. Visible text and pictures, "
            "including visible annotation appearances, remain. This is not redaction or an "
            "anonymity guarantee. Originals are preserved; output uses a neutral filename.",
        ),
    )

    def validate_input(self, input_path):
        return PdfImagesConverter(FileFormat.PNG).validate_input(input_path)

    def validate_options(self, options):
        dpi = options.get("dpi", 150)
        if set(options) - {"dpi"} or type(dpi) is not int or dpi not in (72, 150, 300):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Choose 72, 150 or 300 DPI.")
        return {"dpi": dpi}

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        dpi = self.validate_options(options)["dpi"]
        cancel_token.raise_if_cancelled()
        name = f"clean-document-{uuid4().hex[:12]}.pdf"
        report_name = Path(name).stem + ".report.json"
        try:
            with (
                PdfImagesConverter(FileFormat.PNG)._open(Path(input_path)) as source,
                pymupdf.open() as clean,
                OutputTransaction(Path(output_dir)) as output,
            ):
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
                            "Page exceeds the pixel limit; choose a lower DPI.",
                        )
                    pixels = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
                    target = clean.new_page(width=page.rect.width, height=page.rect.height)
                    target.insert_image(target.rect, stream=pixels.tobytes("png"))
                    del pixels
                    progress(Progress(index, len(source)))
                cancel_token.raise_if_cancelled()
                clean.save(output.staging / name, garbage=4, deflate=True, no_new_id=True)
                with pymupdf.open(output.staging / name) as verified:
                    if (
                        verified.page_count != source.page_count
                        or verified.embfile_count()
                        or verified.get_xml_metadata()
                        or any(
                            verified.metadata.get(key)
                            for key in (
                                "author",
                                "creator",
                                "producer",
                                "title",
                                "subject",
                                "keywords",
                                "creationDate",
                                "modDate",
                            )
                        )
                    ):
                        raise ConversionError(
                            ErrorCode.CONVERSION_FAILED, "PDF privacy verification failed."
                        )
                report = {
                    "tool": "metadata.clean_pdf",
                    "pages": len(source),
                    "dpi": dpi,
                    "policy": "New PDF from rendered pixels only; no source PDF objects copied.",
                    "policy_categories": [
                        "document properties/XMP",
                        "attachments",
                        "scripts",
                        "hidden text",
                        "interactive forms/annotations",
                        "links",
                    ],
                    "limits": "Visible content remains. Text is no longer selectable. "
                    "Pixel steganography, filesystem metadata and personal content "
                    "are not anonymized. Technical PDF structure remains.",
                }
                (output.staging / report_name).write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                return output.publish([name, report_name], cancel_token)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED,
                "Cannot rebuild or save this PDF; check permissions and input.",
            ) from exc
