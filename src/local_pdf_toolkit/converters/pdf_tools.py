"""Offline PDF edits and text exports, always staged without changing sources."""

import re
import secrets
from contextlib import ExitStack
from pathlib import Path

import pymupdf

from local_pdf_toolkit.converters.pdf_images import (
    MAX_INPUT_BYTES,
    MAX_PAGES,
    PdfImagesConverter,
    page_selection,
)
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction


def _option(name, label, default, description, choices=(), minimum=None, maximum=None):
    return OptionDefinition(name, label, default, description, choices, minimum, maximum)


PAGES = _option("pages", "Pages", "all", "All pages or a range such as 1,3-5.")
PASSWORD = _option("password", "Password", "", "Required; at most 127 UTF-8 bytes.")
OPERATIONS = {
    "merge": ("Merge PDFs", ()),
    "split": ("Split PDF into pages", (PAGES,)),
    "extract": ("Extract PDF pages", (PAGES,)),
    "reorder": (
        "Reorder PDF pages",
        (_option("order", "Page order", "all", "Every page once, such as 3,1-2."),),
    ),
    "delete": ("Delete PDF pages", (PAGES,)),
    "rotate": (
        "Rotate PDF pages",
        (
            PAGES,
            _option(
                "angle", "Clockwise rotation", 90, "Added to current rotation.", (90, 180, 270)
            ),
        ),
    ),
    "crop": (
        "Crop PDF margins",
        (
            PAGES,
            *(
                _option(
                    side,
                    f"{side.title()} margin (pt)",
                    0,
                    "Removed from current crop box.",
                    minimum=0,
                    maximum=100_000,
                )
                for side in ("left", "top", "right", "bottom")
            ),
        ),
    ),
    "number": (
        "Number PDF pages",
        (
            PAGES,
            _option(
                "start",
                "First number",
                1,
                "Numbers selected pages consecutively.",
                minimum=1,
                maximum=1_000_000,
            ),
            _option(
                "font_size",
                "Font size (pt)",
                12,
                "Centered in the bottom margin.",
                minimum=6,
                maximum=72,
            ),
        ),
    ),
    "watermark": (
        "Add text watermark",
        (
            PAGES,
            _option("text", "Watermark text", "DRAFT", "Visible text using a built-in Latin font."),
            _option(
                "font_size",
                "Font size (pt)",
                36,
                "Centered horizontally on each page.",
                minimum=6,
                maximum=200,
            ),
        ),
    ),
    "remove_metadata": ("Remove PDF properties (basic)", ()),
    "flatten": ("Flatten PDF annotations and forms", ()),
    "protect": (
        "Protect PDF with password",
        (_option("password", "Password", "", "Required; up to 40 characters / 127 UTF-8 bytes."),),
    ),
    "unlock": ("Unlock PDF with password", (PASSWORD,)),
    "to_text": ("PDF to text", (PAGES,)),
    "to_markdown": ("PDF to Markdown", (PAGES,)),
}


def ordered_pages(text: str, count: int) -> tuple[int, ...]:
    """Read a complete page permutation without sorting away the user's order."""
    if text.strip().lower() == "all" or not text.strip():
        return tuple(range(count))
    result = []
    for part in text.split(","):
        match = re.fullmatch(r"\s*(\d+)(?:\s*-\s*(\d+))?\s*", part)
        if not match:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Use an order such as 3,1-2.")
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Pages must be within 1–{count}.")
        result.extend(range(first - 1, last))
        if len(result) > count:
            break
    if len(result) != count or len(set(result)) != count:
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Include every page exactly once.")
    return tuple(result)


def _safe_stem(path):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", path.stem).rstrip(" .")[:100]
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if stem.partition(".")[0].upper() in reserved:
        stem = "_" + stem
    return stem or "document"


class PdfToolConverter:
    def __init__(self, operation):
        if operation not in OPERATIONS:
            raise ValueError("Unknown PDF operation.")
        self.operation = operation
        label, options = OPERATIONS[operation]
        output = {"to_text": FileFormat.TXT, "to_markdown": FileFormat.MARKDOWN}.get(
            operation, FileFormat.PDF
        )
        limitations = []
        if operation in ("to_text", "to_markdown"):
            limitations.append("Extracts existing text only; no OCR or layout reconstruction.")
        if operation == "to_markdown":
            limitations.append("Markdown contains page headings and extracted plain text.")
        if operation == "crop":
            limitations.append("Cropping hides content; it does not securely redact it.")
        if operation in ("watermark", "number"):
            limitations.append("Uses a built-in Latin font; existing content can be overlaid.")
        if operation == "remove_metadata":
            limitations.append(
                "Removes document Info and XMP metadata, not page text or attachments."
            )
        if operation == "flatten":
            limitations.append(
                "Makes annotation and form appearances permanent and noninteractive."
            )
        self.spec = ConverterSpec(
            f"pdf.{operation}",
            label,
            (FileFormat.PDF,),
            (output,),
            tuple(options),
            tuple(limitations),
            input_mode="multiple" if operation == "merge" else "single",
        )

    def _open(self, path):
        return PdfImagesConverter(FileFormat.PNG)._open(path)

    def _open_unlock(self, path, password=None):
        """Validate encrypted documents without mistaking parser repair for success."""
        document = None
        try:
            if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
                raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a PDF up to 512 MiB.")
            with path.open("rb") as stream:
                if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                    raise ConversionError(ErrorCode.INVALID_INPUT, "The file is not a PDF.")
            document = pymupdf.open(path)
            if not document.is_pdf or document.is_repaired:
                raise ConversionError(ErrorCode.INVALID_INPUT, "PDF is damaged or invalid.")
            encrypted = document.needs_pass or bool(document.metadata.get("encryption"))
            if not encrypted:
                raise ConversionError(ErrorCode.INVALID_INPUT, "The PDF is not password protected.")
            if password is not None and not document.authenticate(password):
                raise ConversionError(ErrorCode.PASSWORD_REQUIRED, "The PDF password is incorrect.")
            if not 0 < document.page_count <= MAX_PAGES:
                raise ConversionError(
                    ErrorCode.INVALID_INPUT, "PDF exceeds the page limit or is empty."
                )
            return document
        except ConversionError:
            if document is not None:
                document.close()
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            if document is not None:
                document.close()
            raise ConversionError(ErrorCode.INVALID_INPUT, f"Cannot open PDF: {exc}") from exc

    def validate_input(self, input_path):
        if self.operation == "merge":
            paths = self._inputs(input_path)
            for path in paths:
                with self._open(path):
                    pass
        else:
            path = self._inputs(input_path)[0]
            opener = self._open_unlock if self.operation == "unlock" else self._open
            with opener(path):
                pass
        return FileFormat.PDF

    def _inputs(self, value):
        if self.operation == "merge":
            if not isinstance(value, tuple) or not 2 <= len(value) <= MAX_PAGES:
                raise ConversionError(
                    ErrorCode.INVALID_INPUT, "Choose at least two ordered PDF files."
                )
            if not all(isinstance(path, str | Path) for path in value):
                raise ConversionError(ErrorCode.INVALID_INPUT, "Choose regular PDF files.")
            return tuple(Path(path) for path in value)
        if not isinstance(value, str | Path):
            raise ConversionError(ErrorCode.INVALID_INPUT, "Choose one PDF file.")
        return (Path(value),)

    def validate_options(self, options):
        definitions = {item.name: item for item in self.spec.options}
        if set(options) - definitions.keys():
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown conversion option.")
        values = {name: options.get(name, item.default) for name, item in definitions.items()}
        for name, item in definitions.items():
            value = values[name]
            if type(value) is not type(item.default):
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {item.label}.")
            if item.choices and value not in item.choices:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Unsupported {item.label}.")
            if item.minimum is not None and value < item.minimum:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"{item.label} is too small.")
            if item.maximum is not None and value > item.maximum:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"{item.label} is too large.")
            if isinstance(value, str) and len(value) > 4096:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"{item.label} is too long.")
        if "password" in values:
            if not values["password"] or len(values["password"].encode("utf-8")) > 127:
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "Provide a password of 1–127 UTF-8 bytes."
                )
            if self.operation == "protect" and len(values["password"]) > 40:
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "New PDF passwords must be at most 40 characters."
                )
        if "text" in values:
            text = values["text"]
            if not text.strip() or any(ord(char) < 32 or ord(char) > 255 for char in text):
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "Use nonempty, single-line Latin text."
                )
        return values

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        values = self.validate_options(options)
        paths = self._inputs(input_path)
        cancel_token.raise_if_cancelled()
        try:
            with ExitStack() as stack:
                # Open sources one at a time for merge to bound file descriptors and memory.
                if self.operation == "merge":
                    document = stack.enter_context(pymupdf.open())
                else:
                    document = stack.enter_context(
                        self._open_unlock(paths[0], values["password"])
                        if self.operation == "unlock"
                        else self._open(paths[0])
                    )
                with OutputTransaction(Path(output_dir)) as outputs:
                    stem = _safe_stem(paths[0])
                    if self.operation == "merge":
                        self._merge(document, paths, progress, cancel_token)
                    names = self._produce(document, stem, values, outputs, progress, cancel_token)
                    cancel_token.raise_if_cancelled()
                    return outputs.publish(names, cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                f"Cannot write outputs: {exc}. "
                "Check permissions, free space and existing filenames.",
            ) from exc
        except (RuntimeError, ValueError, OverflowError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"PDF operation failed: {exc}"
            ) from exc

    def _merge(self, document, paths, progress, token):
        progress(Progress(0, len(paths)))
        total_bytes = 0
        for completed, path in enumerate(paths, 1):
            token.raise_if_cancelled()
            with self._open(path) as source:
                total_bytes += path.stat().st_size
                if len(document) + len(source) > MAX_PAGES or total_bytes > MAX_INPUT_BYTES:
                    raise ConversionError(
                        ErrorCode.INVALID_INPUT, "Merged input exceeds resource limits."
                    )
                document.insert_pdf(source)
            progress(Progress(completed, len(paths)))

    def _produce(self, document, stem, values, outputs, progress, token):
        operation = self.operation
        pages = page_selection(values.get("pages", "all"), len(document))
        if operation in ("to_text", "to_markdown"):
            extension = "txt" if operation == "to_text" else "md"
            name = f"{stem}.{extension}"
            progress(Progress(0, len(pages)))
            with (outputs.staging / name).open("w", encoding="utf-8", newline="\n") as stream:
                for completed, index in enumerate(pages, 1):
                    token.raise_if_cancelled()
                    if operation == "to_markdown":
                        stream.write(f"## Page {index + 1}\n\n")
                    stream.write(document[index].get_text(sort=True))
                    stream.write("\n\n" if operation == "to_markdown" else "\f\n")
                    progress(Progress(completed, len(pages)))
            return [name]
        if operation == "split":
            names = []
            progress(Progress(0, len(pages)))
            for completed, index in enumerate(pages, 1):
                token.raise_if_cancelled()
                name = f"{stem}_page-{index + 1:04d}.pdf"
                with pymupdf.open() as result:
                    result.insert_pdf(document, from_page=index, to_page=index)
                    result.save(outputs.staging / name, garbage=4)
                names.append(name)
                progress(Progress(completed, len(pages)))
            return names
        if operation == "extract":
            document.select(pages)
        elif operation == "reorder":
            document.select(ordered_pages(values["order"], len(document)))
        elif operation == "delete":
            if len(pages) == len(document):
                raise ConversionError(ErrorCode.INVALID_OPTIONS, "At least one page must remain.")
            document.delete_pages(list(pages))
        elif operation in ("rotate", "crop", "number", "watermark"):
            progress(Progress(0, len(pages)))
            for completed, index in enumerate(pages, 1):
                token.raise_if_cancelled()
                page = document[index]
                self._edit_page(page, values, completed)
                progress(Progress(completed, len(pages)))
        elif operation == "remove_metadata":
            document.set_metadata({})
            document.del_xml_metadata()
        elif operation == "flatten":
            token.raise_if_cancelled()
            document.bake(annots=True, widgets=True)
        token.raise_if_cancelled()
        name = f"{stem}_{operation}.pdf"
        kwargs = {"garbage": 4, "encryption": pymupdf.PDF_ENCRYPT_NONE}
        if operation == "protect":
            kwargs.update(
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                owner_pw=secrets.token_urlsafe(24),
                user_pw=values["password"],
            )
        document.save(outputs.staging / name, **kwargs)
        if operation not in ("merge", "rotate", "crop", "number", "watermark"):
            progress(Progress(1, 1))
        return [name]

    def _edit_page(self, page, values, completed):
        if self.operation == "rotate":
            page.set_rotation((page.rotation + values["angle"]) % 360)
        elif self.operation == "crop":
            box = page.cropbox
            box = pymupdf.Rect(
                box.x0 + values["left"],
                box.y0 + values["top"],
                box.x1 - values["right"],
                box.y1 - values["bottom"],
            )
            if box.is_empty or box.is_infinite:
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "Crop margins remove the entire page."
                )
            page.set_cropbox(box)
        else:
            text = (
                str(values["start"] + completed - 1)
                if self.operation == "number"
                else values["text"]
            )
            size = values["font_size"]
            # Place text in the displayed page, then map its origin to PDF coordinates.
            rect = page.rect
            width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
            if width + 12 > rect.width or size * 2 > rect.height:
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "Text does not fit; use a smaller font."
                )
            point = (
                (rect.width - width) / 2,
                rect.height - size if self.operation == "number" else rect.height / 2,
            )
            page.insert_text(
                pymupdf.Point(point) * page.derotation_matrix,
                text,
                fontsize=size,
                fontname="helv",
                rotate=page.rotation,
                overlay=True,
                color=(0.45, 0.45, 0.45),
                fill_opacity=1 if self.operation == "number" else 0.3,
            )


def pdf_tool_converters():
    """Return registered adapters in stable display order."""
    return tuple(PdfToolConverter(operation) for operation in OPERATIONS)
