"""Optional offline OCR using a separately installed Tesseract executable."""

import contextlib
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pymupdf

from local_pdf_toolkit.converters.pdf_images import MAX_PAGES, MAX_PIXELS, PdfImagesConverter
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_PROCESS_OUTPUT = 64 * 1024
MAX_OCR_PAGE_BYTES = 256 * 1024 * 1024


def find_tesseract():
    """Find a local installation; never download engines or language packs."""
    for executable in ("tesseract", "tesseract.exe"):
        if found := shutil.which(executable):
            return Path(found)
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            if base := os.environ.get(variable):
                candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
                if candidate.is_file():
                    return candidate
    return None


def _stop_process_tree(process):
    """Reap the child and terminate descendants on failure or cancellation."""
    if os.name == "nt":
        if process.poll() is None:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
    finally:
        if os.name != "nt":
            # Also catch descendants whose supervisor already exited.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)


def _run(command, timeout, cancel_token, *, output_path=None):
    """Capture bounded diagnostics and poll cancellation without blocking on pipes."""
    cancel_token.raise_if_cancelled()
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    captured = bytearray()
    overflow = threading.Event()

    def read_output():
        while chunk := process.stdout.read(4096):
            remaining = MAX_PROCESS_OUTPUT - len(captured)
            captured.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.set()

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            cancel_token.raise_if_cancelled()
            if time.monotonic() >= deadline:
                raise ConversionError(ErrorCode.CONVERSION_FAILED, "Tesseract OCR timed out.")
            if overflow.is_set():
                raise ConversionError(
                    ErrorCode.CONVERSION_FAILED, "Tesseract produced excessive diagnostic output."
                )
            if output_path is not None and output_path.exists():
                if output_path.stat().st_size > MAX_OCR_PAGE_BYTES:
                    raise ConversionError(
                        ErrorCode.CONVERSION_FAILED, "Tesseract page output exceeds the size limit."
                    )
            time.sleep(0.05)
        cancel_token.raise_if_cancelled()
    finally:
        _stop_process_tree(process)
        reader.join(timeout=2)
        process.stdout.close()
    if overflow.is_set():
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED, "Tesseract produced excessive diagnostic output."
        )
    if process.returncode:
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED,
            "Tesseract OCR failed. Check that the requested language packs and PDF support "
            "are installed locally.",
        )
    if output_path is not None and output_path.exists():
        if output_path.stat().st_size > MAX_OCR_PAGE_BYTES:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "Tesseract page output exceeds the size limit."
            )
    return captured.decode("utf-8", errors="replace")


class OcrConverter:
    def __init__(self):
        self.spec = ConverterSpec(
            "pdf.ocr",
            "Searchable PDF (Tesseract OCR)",
            (FileFormat.PDF,),
            (FileFormat.PDF,),
            (
                OptionDefinition(
                    "language", "OCR language", "eng", "Installed language codes, e.g. eng+fra."
                ),
                OptionDefinition("dpi", "Resolution (DPI)", 150, "OCR resolution.", (150, 300)),
                OptionDefinition(
                    "timeout",
                    "Timeout per page (seconds)",
                    60,
                    "Maximum Tesseract time for each page.",
                    minimum=5,
                    maximum=120,
                ),
                OptionDefinition(
                    "skip_existing_text",
                    "Keep pages with searchable text",
                    True,
                    "Copy pages containing text; OCR only pages without text.",
                ),
            ),
            (
                "Requires separately installed Tesseract and local language packs; no downloads.",
                "OCR can misread or omit text. OCR pages are rasterized; review the result.",
                "By default any page with existing text is copied unchanged, including mixed "
                "text/image pages; text inside their images is not recognized.",
                "At most 10,000 pages and 40 million rendered pixels per page; "
                "document bookmarks, forms and signatures are not preserved.",
            ),
        )

    def _open(self, path):
        document = PdfImagesConverter(FileFormat.PNG)._open(Path(path))
        if document.page_count > MAX_PAGES:
            document.close()
            raise ConversionError(ErrorCode.INVALID_INPUT, "PDF exceeds the OCR page limit.")
        return document

    def validate_input(self, input_path):
        with self._open(input_path):
            return FileFormat.PDF

    def validate_options(self, options):
        definitions = {option.name: option for option in self.spec.options}
        if set(options) - definitions.keys():
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown OCR option.")
        values = {name: options.get(name, item.default) for name, item in definitions.items()}
        for name, item in definitions.items():
            if type(values[name]) is not type(item.default):
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {item.label}.")
        if values["dpi"] not in (150, 300):
            raise ConversionError(
                ErrorCode.INVALID_OPTIONS, "OCR resolution must be 150 or 300 DPI."
            )
        if not 5 <= values["timeout"] <= 120:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "OCR timeout must be 5–120 seconds.")
        language = values["language"]
        if len(language) > 128 or not re.fullmatch(
            r"[A-Za-z0-9_-]+(?:\+[A-Za-z0-9_-]+)*", language
        ):
            raise ConversionError(
                ErrorCode.INVALID_OPTIONS,
                "Use installed language codes such as eng or eng+fra "
                "(letters, digits, underscores and hyphens; at most 128 characters).",
            )
        return values

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        options = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(input_path).stem).rstrip(" .")[:100]
        name = f"{stem or 'document'}_searchable.pdf"
        try:
            with self._open(input_path) as source:
                binary = find_tesseract()
                if binary is None:
                    raise ConversionError(
                        ErrorCode.CONVERSION_FAILED,
                        "Tesseract is not installed. Install it and OCR language packs locally.",
                    )
                installed = set(_run([str(binary), "--list-langs"], 5, cancel_token).splitlines())
                missing = set(options["language"].split("+")) - installed
                if missing:
                    raise ConversionError(
                        ErrorCode.INVALID_OPTIONS,
                        "Tesseract language packs are not installed: "
                        + ", ".join(sorted(missing))
                        + ". Install them locally before running OCR.",
                    )
                with (
                    OutputTransaction(Path(output_dir)) as outputs,
                    tempfile.TemporaryDirectory(prefix="pdf-toolkit-ocr-") as temporary,
                    pymupdf.open() as result,
                ):
                    if (outputs.directory / name).exists():
                        raise ConversionError(ErrorCode.OUTPUT_ERROR, "Output already exists.")
                    work = Path(temporary)
                    progress(Progress(0, len(source)))
                    for index, page in enumerate(source):
                        cancel_token.raise_if_cancelled()
                        if options["skip_existing_text"] and page.get_text("text").strip():
                            result.insert_pdf(source, from_page=index, to_page=index)
                        else:
                            self._ocr_page(page, result, binary, work, options, cancel_token)
                        progress(Progress(index + 1, len(source)))
                    cancel_token.raise_if_cancelled()
                    result.save(outputs.staging / name, garbage=4, deflate=True)
                    cancel_token.raise_if_cancelled()
                    return outputs.publish([name], cancel_token)
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "Cannot run Tesseract or write the output PDF. Check installation, permissions "
                "and free space.",
            ) from exc
        except (RuntimeError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "PDF OCR processing failed."
            ) from exc

    def _ocr_page(self, page, result, binary, work, options, cancel_token):
        rotation = page.rotation
        try:
            # OCR the unrotated crop area, then restore its original PDF geometry.
            page.set_rotation(0)
            scale = options["dpi"] / 72
            if (
                math.ceil(page.rect.width * scale) * math.ceil(page.rect.height * scale)
                > MAX_PIXELS
            ):
                raise ConversionError(
                    ErrorCode.INVALID_INPUT,
                    "Page exceeds 40 million rendered pixels. Try a lower OCR DPI.",
                )
            image = work / "page.png"
            produced = work / "page.pdf"
            produced.unlink(missing_ok=True)
            pixmap = page.get_pixmap(dpi=options["dpi"], colorspace=pymupdf.csRGB, alpha=False)
            cancel_token.raise_if_cancelled()
            pixmap.save(image)
            del pixmap
            _run(
                [
                    str(binary),
                    str(image),
                    str(work / "page"),
                    "-l",
                    options["language"],
                    "--dpi",
                    str(options["dpi"]),
                    "pdf",
                ],
                options["timeout"],
                cancel_token,
                output_path=produced,
            )
            cancel_token.raise_if_cancelled()
            with self._open(produced) as recognized:
                if len(recognized) != 1:
                    raise ConversionError(
                        ErrorCode.CONVERSION_FAILED, "Tesseract did not produce a single-page PDF."
                    )
                target = result.new_page(width=page.mediabox.width, height=page.mediabox.height)
                target.set_mediabox(page.mediabox)
                target.set_cropbox(page.cropbox)
                # UserUnit scales physical page dimensions beyond its PDF boxes.
                user_unit = page.rect.width / page.cropbox.width
                if not math.isclose(user_unit, 1):
                    result.xref_set_key(target.xref, "UserUnit", f"{user_unit:.12g}")
                    target = result.reload_page(target)
                target.show_pdf_page(target.rect, recognized, 0, keep_proportion=False)
                target.set_rotation(rotation)
        finally:
            page.set_rotation(rotation)


def ocr_converters():
    return (OcrConverter(),)
