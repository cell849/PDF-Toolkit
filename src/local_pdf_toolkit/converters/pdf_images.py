"""Incremental PDF rasterization. Called inside one dedicated worker process."""

import math
import re
from pathlib import Path

from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_PAGES = 10_000
MAX_PIXELS = 40_000_000


def page_selection(text: str, count: int) -> tuple[int, ...]:
    if not text.strip() or text.strip().lower() == "all":
        return tuple(range(count))
    selected = set()
    for part in text.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not match:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Use pages such as 1,3-5 or all.")
        first = int(match[1])
        last = int(match[2] or first)
        if not 1 <= first <= last <= count:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Pages must be within 1–{count}.")
        selected.update(range(first - 1, last))
    return tuple(sorted(selected))


class PdfImagesConverter:
    def __init__(self, output_format: FileFormat) -> None:
        if output_format not in (FileFormat.JPEG, FileFormat.PNG):
            raise ValueError("Only JPEG and PNG rendering are supported.")
        self.output_format = output_format
        options = [
            OptionDefinition("pages", "Pages", "all", "All pages or a range such as 1,3-5."),
            OptionDefinition(
                "dpi",
                "Resolution (DPI)",
                150,
                "Rendering resolution (10–1200).",
                minimum=10,
                maximum=1200,
            ),
        ]
        if output_format == FileFormat.JPEG:
            options.append(
                OptionDefinition("quality", "JPEG quality", 85, "1–100.", minimum=1, maximum=100)
            )
        else:
            options.append(
                OptionDefinition(
                    "alpha",
                    "Transparent background",
                    False,
                    "Preserve transparent areas instead of using white.",
                )
            )
        self.spec = ConverterSpec(
            f"pdf.to_{output_format.value}",
            f"PDF to {output_format.value.upper()}",
            (FileFormat.PDF,),
            (output_format,),
            tuple(options),
            ("Images rasterize text and vectors; text will no longer be selectable.",),
        )

    def _open(self, path):
        import pymupdf

        try:
            if not path.is_file():
                raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a regular PDF file.")
            if path.stat().st_size > MAX_INPUT_BYTES:
                raise ConversionError(ErrorCode.INVALID_INPUT, "PDF exceeds the 512 MiB limit.")
            with path.open("rb") as stream:
                if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                    raise ConversionError(ErrorCode.INVALID_INPUT, "The file is not a PDF.")
            document = pymupdf.open(path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConversionError(ErrorCode.INVALID_INPUT, f"Cannot open PDF: {exc}") from exc
        if document.needs_pass:
            document.close()
            raise ConversionError(
                ErrorCode.PASSWORD_REQUIRED, "Password-protected PDFs are unsupported."
            )
        if not document.is_pdf or document.is_repaired or not 0 < document.page_count <= MAX_PAGES:
            document.close()
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "PDF is damaged, empty, or exceeds the 10,000-page limit."
            )
        return document

    def validate_input(self, input_path: Path) -> FileFormat:
        with self._open(Path(input_path)):
            return FileFormat.PDF

    def validate_options(self, options):
        definitions = {option.name: option for option in self.spec.options}
        if set(options) - definitions.keys():
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown conversion option.")
        values = {
            name: options.get(name, definition.default) for name, definition in definitions.items()
        }
        for name, definition in definitions.items():
            value = values[name]
            if type(value) is not type(definition.default):
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, f"Invalid value for {definition.label}."
                )
            if definition.choices and value not in definition.choices:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Unsupported {definition.label}.")
            if (
                definition.minimum is not None
                and not definition.minimum <= value <= definition.maximum
            ):
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS,
                    f"{definition.label} must be {definition.minimum}–{definition.maximum}.",
                )
        if len(values["pages"]) > 4096:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Page range is too long.")
        return values

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        import pymupdf

        options = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        extension = "jpg" if self.output_format == FileFormat.JPEG else "png"
        # Make even POSIX source names safe for a later Windows copy.
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(input_path).stem).rstrip(" .")[:100]
        stem = stem or "document"
        try:
            with self._open(Path(input_path)) as document:
                pages = page_selection(options["pages"], len(document))
                names = [f"{stem}_page-{page + 1:04d}.{extension}" for page in pages]
                with OutputTransaction(Path(output_dir)) as outputs:
                    if any((outputs.directory / name).exists() for name in names):
                        raise ConversionError(
                            ErrorCode.OUTPUT_ERROR,
                            "Output already exists. Choose another folder or move it.",
                        )
                    progress(Progress(0, len(pages)))
                    for completed, (index, name) in enumerate(zip(pages, names, strict=True), 1):
                        cancel_token.raise_if_cancelled()
                        page = document[index]
                        scale = options["dpi"] / 72
                        if (
                            math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale)
                            > MAX_PIXELS
                        ):
                            raise ConversionError(
                                ErrorCode.INVALID_INPUT,
                                "Page exceeds 40 million pixels. Try a lower DPI.",
                            )
                        pixmap = page.get_pixmap(
                            dpi=options["dpi"],
                            colorspace=pymupdf.csRGB,
                            alpha=options.get("alpha", False),
                        )
                        cancel_token.raise_if_cancelled()
                        kwargs = {"jpg_quality": options["quality"]} if extension == "jpg" else {}
                        pixmap.save(outputs.staging / name, **kwargs)
                        del pixmap
                        progress(Progress(completed, len(pages)))
                    return outputs.publish(names, cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                f"Cannot write outputs: {exc}. Check permissions and free space.",
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"PDF rendering failed: {exc}"
            ) from exc
