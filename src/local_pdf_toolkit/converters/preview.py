"""One bounded preview page per worker job; all outputs belong to a temporary dialog."""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from PIL import Image

from local_pdf_toolkit.converters.images import FORMATS, open_image
from local_pdf_toolkit.converters.office_pdf import OfficePdfConverter
from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.core.contracts import ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction


class PreviewConverter:
    spec = ConverterSpec(
        "preview.page", "Preview page", (FileFormat.PDF, FileFormat.PNG), (FileFormat.PNG,)
    )

    def validate_options(self, options):
        page = options.get("page", 1)
        if set(options) - {"page"} or type(page) is not int or not 1 <= page <= 10000:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Choose a valid page number.")
        return {"page": page}

    def validate_input(self, path):
        with Path(path).open("rb") as source:
            header = source.read(1024)
        if header.lstrip().startswith(b"%PDF-"):
            return PdfImagesConverter(FileFormat.PNG).validate_input(path)
        if header.startswith(b"PK") and Path(path).suffix.lower() in (
            ".docx",
            ".xlsx",
            ".pptx",
            ".odt",
            ".ods",
            ".odp",
            ".rtf",
            ".txt",
            ".csv",
        ):
            return OfficePdfConverter().validate_input(path)
        if header.startswith(b"{\\rtf") or Path(path).suffix.lower() in (".txt", ".csv"):
            return OfficePdfConverter().validate_input(path)
        with open_image(path) as image:
            return FORMATS[image.format]

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        import pymupdf

        page_number = self.validate_options(options)["page"]
        path = Path(input_path)
        cancel_token.raise_if_cancelled()
        token = uuid4().hex[:12]
        name = f"preview-{token}.png"
        info_name = f"preview-{token}.json"
        try:
            with (
                tempfile.TemporaryDirectory(prefix="pdf-toolkit-preview-") as scratch,
                OutputTransaction(Path(output_dir)) as output,
            ):
                snapshot = Path(scratch) / ("source" + path.suffix)
                digest = hashlib.sha256()
                total = 0
                with path.open("rb") as original, snapshot.open("xb") as target:
                    while chunk := original.read(1024 * 1024):
                        cancel_token.raise_if_cancelled()
                        total += len(chunk)
                        if total > 512 * 1024 * 1024:
                            raise ConversionError(
                                ErrorCode.INVALID_INPUT, "Preview exceeds 512 MiB."
                            )
                        digest.update(chunk)
                        target.write(chunk)
                path = snapshot
                kind = self.validate_input(path)
                prepared = None
                office = kind not in (FileFormat.PDF, *FORMATS.values())
                if office:
                    pdfs = OfficePdfConverter().convert(
                        path, Path(scratch), {}, lambda _: None, cancel_token
                    )
                    path = pdfs[0]
                    prepared = f"preview-{token}.pdf"
                    shutil.copyfile(path, output.staging / prepared)
                    kind = FileFormat.PDF
                cancel_token.raise_if_cancelled()
                if kind == FileFormat.PDF:
                    with PdfImagesConverter(FileFormat.PNG)._open(path) as document:
                        count = len(document)
                        if page_number > count:
                            raise ConversionError(
                                ErrorCode.INVALID_OPTIONS, "Page is outside this document."
                            )
                        page = document[page_number - 1]
                        scale = min(2.0, 1400 / max(page.rect.width, page.rect.height))
                        pixmap = page.get_pixmap(
                            matrix=pymupdf.Matrix(scale, scale),
                            colorspace=pymupdf.csRGB,
                            alpha=False,
                        )
                        pixmap.save(output.staging / name)
                        info = {
                            "pages": count,
                            "page": page_number,
                            "width": pixmap.width,
                            "height": pixmap.height,
                            "native_width": page.rect.width,
                            "native_height": page.rect.height,
                            "native_unit": "pt",
                            "office_approximation": office,
                        }
                else:
                    if page_number != 1:
                        raise ConversionError(ErrorCode.INVALID_OPTIONS, "This image has one page.")
                    with open_image(path) as image:
                        native_width, native_height = image.size
                        image.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
                        with (
                            image.convert("RGBA") as rgba,
                            Image.frombytes("RGBA", rgba.size, rgba.tobytes()) as fresh,
                        ):
                            fresh.save(output.staging / name, format="PNG")
                            info = {
                                "pages": 1,
                                "page": 1,
                                "width": fresh.width,
                                "height": fresh.height,
                                "native_width": native_width,
                                "native_height": native_height,
                                "native_unit": "px",
                                "office_approximation": False,
                            }
                cancel_token.raise_if_cancelled()
                info["source_sha256"] = digest.hexdigest()
                info["source_bytes"] = total
                (output.staging / info_name).write_text(json.dumps(info), encoding="utf-8")
                progress(Progress(1, 1))
                return output.publish(
                    [name, info_name] + ([prepared] if prepared else []), cancel_token
                )
        except (OSError, ValueError, RuntimeError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "Cannot render this preview."
            ) from exc
