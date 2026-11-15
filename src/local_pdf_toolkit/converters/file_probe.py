"""Small, private file descriptions, produced in a worker without optional processes."""

import json
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from local_pdf_toolkit.converters.images import FORMATS, open_image
from local_pdf_toolkit.converters.media_metadata import inspect_media
from local_pdf_toolkit.converters.office_pdf import OfficePdfConverter, find_libreoffice
from local_pdf_toolkit.converters.pdf_images import MAX_INPUT_BYTES, PdfImagesConverter
from local_pdf_toolkit.core.contracts import CancellationToken, ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

_ROOTS = {
    "word/document.xml": "docx",
    "xl/workbook.xml": "xlsx",
    "ppt/presentation.xml": "pptx",
}
_MIMES = {
    b"application/vnd.oasis.opendocument.text": "odt",
    b"application/vnd.oasis.opendocument.spreadsheet": "ods",
    b"application/vnd.oasis.opendocument.presentation": "odp",
}
_MEDIA = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"}


class FileProbeConverter:
    """Read basic geometry and parser acceptance, never author names or tag values.

    ``ready`` describes acceptance for the requested input formats. Optional
    engines are reported separately. Only media inspection invokes FFprobe;
    probing never starts a conversion engine.
    """

    spec = ConverterSpec("inspect.file", "Inspect file", tuple(FileFormat), (FileFormat.JSON,))

    def validate_options(self, options):
        formats = options.get("formats", "")
        if isinstance(formats, list | tuple):
            formats = ",".join(str(item) for item in formats)
        if set(options) - {"formats"} or not isinstance(formats, str):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid inspection options.")
        try:
            kinds = tuple(FileFormat(item.strip()) for item in formats.split(",") if item.strip())
        except ValueError as exc:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown input format.") from exc
        return {"formats": kinds}

    def validate_input(self, path):
        # Protocol compatibility; callers normally use convert for its report.
        with tempfile.TemporaryDirectory(prefix="pdf-toolkit-probe-") as temporary:
            report = self._inspect(Path(path), Path(temporary), None)
        return FileFormat(report["format"])

    def _inspect(self, source, temporary, token):
        if not source.is_file() or not 0 < source.stat().st_size <= MAX_INPUT_BYTES:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Choose a file below 512 MiB.")
        snapshot = temporary / "source.bin"
        size = 0
        with source.open("rb") as original, snapshot.open("xb") as target:
            while chunk := original.read(1024 * 1024):
                if token is not None:
                    token.raise_if_cancelled()
                size += len(chunk)
                if size > MAX_INPUT_BYTES:
                    raise ConversionError(ErrorCode.INVALID_INPUT, "File exceeds 512 MiB.")
                target.write(chunk)
        if not size:
            raise ConversionError(ErrorCode.INVALID_INPUT, "The file is empty.")
        with snapshot.open("rb") as stream:
            header = stream.read(1024)
        info = {
            "bytes": size,
            "source_bytes": size,
            "pages": None,
            "width": None,
            "height": None,
            "unit": None,
            "dependencies": {},
        }
        if header.lstrip().startswith(b"%PDF-"):
            with PdfImagesConverter(FileFormat.PNG)._open(snapshot) as document:
                rect = document[0].rect
                info.update(
                    format="pdf",
                    pages=len(document),
                    width=rect.width,
                    height=rect.height,
                    unit="pt",
                )
            return info
        media_signature = (
            header.startswith((b"ID3", b"fLaC", b"OggS", b"\x1aE\xdf\xa3"))
            or header[4:8] == b"ftyp"
            or (header.startswith(b"RIFF") and header[8:12] in (b"WAVE", b"AVI "))
        )
        if header.startswith(b"PK"):
            with zipfile.ZipFile(snapshot) as package:
                entries = package.infolist()
                if len(entries) > 20000 or sum(e.file_size for e in entries) > MAX_INPUT_BYTES:
                    raise ConversionError(ErrorCode.INVALID_INPUT, "Office package exceeds limits.")
                names = set(package.namelist())
                kinds = [kind for root, kind in _ROOTS.items() if root in names]
                if "mimetype" in names:
                    entry = package.getinfo("mimetype")
                    if entry.file_size <= 256:
                        kind = _MIMES.get(package.read("mimetype"))
                        if kind:
                            kinds.append(kind)
                if len(kinds) != 1:
                    raise ConversionError(
                        ErrorCode.UNSUPPORTED_FORMAT,
                        "This package is not a supported Office document.",
                    )
                kind = kinds[0]
        elif header.startswith(b"{\\rtf"):
            if size > 16 * 1024 * 1024:
                raise ConversionError(
                    ErrorCode.INVALID_INPUT, "RTF inspection is limited to 16 MiB."
                )
            kind = "rtf"
        else:
            try:
                with open_image(snapshot) as image:
                    info.update(
                        format=FORMATS[image.format].value,
                        pages=1,
                        width=image.width,
                        height=image.height,
                        unit="px",
                    )
                return info
            except ConversionError:
                if source.suffix.lower() in _MEDIA or media_signature:
                    media = inspect_media(snapshot, token or CancellationToken())
                    info.update(format=str(media["format"]), dependencies={"ffmpeg": True})
                    return info
                # Text is verified below; binary input cannot become text by suffix.
                suffix = source.suffix.lower()
                if suffix not in (".txt", ".csv", ".md"):
                    raise ConversionError(
                        ErrorCode.UNSUPPORTED_FORMAT,
                        "No supported document or image format was detected.",
                    ) from None
                if size > 16 * 1024 * 1024:
                    raise ConversionError(
                        ErrorCode.INVALID_INPUT, "Text inspection is limited to 16 MiB."
                    ) from None
                kind = {".csv": "csv", ".md": "md"}.get(suffix, "txt")
        # Office validation checks package contents and never finds or starts an engine.
        # A neutral, content-derived suffix permits detection of renamed packages.
        validated = snapshot.with_suffix(".txt" if kind == "md" else "." + kind)
        snapshot.rename(validated)
        OfficePdfConverter().validate_input(validated)
        info["format"] = kind
        info["dependencies"] = {"libreoffice": find_libreoffice() is not None}
        return info

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        formats = self.validate_options(options)["formats"]
        cancel_token.raise_if_cancelled()
        info = {
            "format": None,
            "bytes": None,
            "source_bytes": None,
            "pages": None,
            "width": None,
            "height": None,
            "unit": None,
            "dependencies": {},
            "ready": False,
            "reason": "",
            "error_code": None,
        }
        try:
            with tempfile.TemporaryDirectory(prefix="pdf-toolkit-probe-") as temporary:
                info.update(self._inspect(Path(input_path), Path(temporary), cancel_token))
            if formats and info["format"] not in formats:
                info.update(
                    reason="This file type is incompatible with the selected tool.",
                    error_code=ErrorCode.UNSUPPORTED_FORMAT.value,
                )
            else:
                info["ready"] = True
        except ConversionError as exc:
            if exc.code == ErrorCode.CANCELLED:
                raise
            if exc.code == ErrorCode.PASSWORD_REQUIRED:
                info.update(format="pdf", encrypted=True)
                try:
                    size = Path(input_path).stat().st_size
                    info.update(bytes=size, source_bytes=size)
                except OSError:
                    pass
            info.update(reason=str(exc), error_code=exc.code.value)
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
            info.update(
                reason="Cannot read or parse this file.", error_code=ErrorCode.INVALID_INPUT.value
            )
        cancel_token.raise_if_cancelled()
        # Alias keys keep the report useful alongside PreviewConverter details.
        info.update(
            native_width=info["width"],
            native_height=info["height"],
            native_unit=info["unit"],
            issue=info["reason"] or None,
        )
        name = f"inspection-{uuid4().hex[:12]}.json"
        with OutputTransaction(Path(output_dir)) as output:
            (output.staging / name).write_text(json.dumps(info), encoding="utf-8")
            paths = output.publish([name], cancel_token)
        progress(Progress(1, 1))
        return paths
