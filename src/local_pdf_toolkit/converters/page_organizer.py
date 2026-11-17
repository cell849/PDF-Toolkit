"""Vector-preserving page assembly bound to reviewed, immutable PDF snapshots."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

from local_pdf_toolkit.converters.pdf_images import MAX_INPUT_BYTES, MAX_PAGES, PdfImagesConverter
from local_pdf_toolkit.converters.pdf_tools import _safe_stem
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_SOURCES = 100
MAX_PLAN_BYTES = 8 * 1024 * 1024
THUMBNAIL_EDGE = 180


def _invalid(message, code=ErrorCode.INVALID_OPTIONS):
    raise ConversionError(code, message)


def canonical_plan(plan):
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def parse_plan(text):
    if type(text) is not str or len(text) > MAX_PLAN_BYTES:
        _invalid("Page plan exceeds the 8 MiB limit.")
    try:
        plan = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid page plan JSON.") from exc
    if type(plan) is not dict or set(plan) != {"version", "sources", "pages"}:
        _invalid("Invalid page plan structure.")
    if type(plan["version"]) is not int or plan["version"] != 1:
        _invalid("Unsupported page plan version.")
    sources, pages = plan["sources"], plan["pages"]
    if type(sources) is not list or not 1 <= len(sources) <= MAX_SOURCES:
        _invalid("Choose 1–100 PDF sources.")
    known = {}
    for source in sources:
        if type(source) is not dict or set(source) != {
            "path",
            "size",
            "mtime_ns",
            "sha256",
            "pages",
        }:
            _invalid("Invalid PDF source snapshot.")
        path = source["path"]
        if (
            type(path) is not str
            or not path
            or len(path) > 32768
            or "\x00" in path
            or not Path(path).is_absolute()
            or str(Path(path).resolve()) != path
            or path in known
        ):
            _invalid("PDF source paths must be unique absolute canonical paths.")
        if any(type(source[key]) is not int for key in ("size", "mtime_ns", "pages")):
            _invalid("Invalid PDF source signature.")
        if not 0 < source["size"] <= MAX_INPUT_BYTES or source["mtime_ns"] < 0:
            _invalid("Invalid PDF source size or timestamp.")
        if not 0 < source["pages"] <= MAX_PAGES:
            _invalid("Invalid PDF source page count.")
        if type(source["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", source["sha256"]):
            _invalid("Invalid PDF source digest.")
        known[path] = source
    if sum(source["size"] for source in sources) > MAX_INPUT_BYTES:
        _invalid("Combined sources exceed 512 MiB.")
    if sum(source["pages"] for source in sources) > MAX_PAGES:
        _invalid("Combined sources exceed 10,000 pages.")
    if type(pages) is not list or not 1 <= len(pages) <= MAX_PAGES:
        _invalid("Keep at least one page, with at most 10,000 pages.")
    for page in pages:
        if type(page) is not dict or set(page) != {"path", "page", "rotation"}:
            _invalid("Invalid page entry.")
        if type(page["path"]) is not str or page["path"] not in known:
            _invalid("Page references an unapproved PDF source.")
        if type(page["page"]) is not int or not 1 <= page["page"] <= known[page["path"]]["pages"]:
            _invalid("Page number is outside its source PDF.")
        if type(page["rotation"]) is not int or page["rotation"] not in (0, 90, 180, 270):
            _invalid("Page rotation must be 0, 90, 180 or 270 degrees.")
    return plan


def _inputs(value):
    if not isinstance(value, tuple) or not 1 <= len(value) <= MAX_SOURCES:
        _invalid("Choose 1–100 PDF files.", ErrorCode.INVALID_INPUT)
    if not all(isinstance(path, str | Path) for path in value):
        _invalid("Choose regular PDF files.", ErrorCode.INVALID_INPUT)
    paths = tuple(Path(path).resolve() for path in value)
    if len(set(paths)) != len(paths):
        _invalid("Choose each PDF source once.", ErrorCode.INVALID_INPUT)
    return paths


def _open(path):
    document = PdfImagesConverter(FileFormat.PNG)._open(path)
    if document.metadata.get("encryption"):
        document.close()
        _invalid("Unlock PDFs before organizing their pages.", ErrorCode.PASSWORD_REQUIRED)
    return document


def _snapshot(path, destination, token, expected=None, maximum_bytes=None):
    """Copy and hash bounded chunks, then only parse the private bytes that were hashed."""
    digest, size = hashlib.sha256(), 0
    limit = MAX_INPUT_BYTES if maximum_bytes is None else min(MAX_INPUT_BYTES, maximum_bytes)
    try:
        if not path.is_file():
            _invalid("Choose regular PDF files.", ErrorCode.INVALID_INPUT)
        with path.open("rb") as source, destination.open("xb") as target:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
                _invalid("Choose regular PDFs up to 512 MiB.", ErrorCode.INVALID_INPUT)
            if expected and (before.st_size, before.st_mtime_ns) != (
                expected["size"],
                expected["mtime_ns"],
            ):
                _invalid("A PDF changed. Reload its pages before saving.", ErrorCode.INVALID_INPUT)
            while True:
                token.raise_if_cancelled()
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    _invalid("PDF exceeds 512 MiB.", ErrorCode.INVALID_INPUT)
                target.write(chunk)
                digest.update(chunk)
            after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                _invalid(
                    "A PDF changed while reading it. Reload its pages.", ErrorCode.INVALID_INPUT
                )
        if expected and (size != expected["size"] or digest.hexdigest() != expected["sha256"]):
            _invalid("A PDF changed. Reload its pages before saving.", ErrorCode.INVALID_INPUT)
        token.raise_if_cancelled()
        with _open(destination) as document:
            count = len(document)
        if expected and count != expected["pages"]:
            _invalid("PDF page count changed. Reload its pages.", ErrorCode.INVALID_INPUT)
        return {
            "path": str(path),
            "size": size,
            "mtime_ns": before.st_mtime_ns,
            "sha256": digest.hexdigest(),
            "pages": count,
        }
    except OSError as exc:
        raise ConversionError(
            ErrorCode.INVALID_INPUT, "Cannot read or snapshot PDF source."
        ) from exc


class PdfPageOrganizerConverter:
    spec = ConverterSpec(
        "pdf.organize_visual",
        "Organize PDF pages visually",
        (FileFormat.PDF,),
        (FileFormat.PDF,),
        (OptionDefinition("plan", "Page arrangement", "", "Arrange pages in the thumbnail grid."),),
        (
            "Saves a new PDF with selectable text and vector graphics. Originals are preserved.",
            "Links, interactive forms, bookmarks, attachments, signatures and document-level "
            "features are not preserved. Annotation and form appearances become permanent.",
        ),
        input_mode="multiple",
    )

    def validate_input(self, input_path):
        total_bytes, total_pages = 0, 0
        for path in _inputs(input_path):
            with _open(path) as source:
                total_bytes += path.stat().st_size
                total_pages += len(source)
            if total_bytes > MAX_INPUT_BYTES or total_pages > MAX_PAGES:
                _invalid("Combined PDFs exceed 512 MiB or 10,000 pages.", ErrorCode.INVALID_INPUT)
        return FileFormat.PDF

    def validate_options(self, options):
        if set(options) - {"plan"}:
            _invalid("Unknown conversion option.")
        return {"plan": canonical_plan(parse_plan(options.get("plan", "")))}

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        import pymupdf

        plan = parse_plan(self.validate_options(options)["plan"])
        paths = _inputs(input_path)
        if set(map(str, paths)) != {source["path"] for source in plan["sources"]}:
            _invalid("Page plan must use exactly the selected PDF sources.")
        cancel_token.raise_if_cancelled()
        try:
            with OutputTransaction(Path(output_dir)) as outputs, pymupdf.open() as result:
                snapshots = {}
                for index, source in enumerate(plan["sources"]):
                    snapshot = outputs.staging / f"source-{index}.pdf"
                    _snapshot(Path(source["path"]), snapshot, cancel_token, source)
                    snapshots[source["path"]] = snapshot
                progress(Progress(0, len(plan["pages"])))
                # One source at a time, even for a plan that alternates between many files.
                source, current_path = None, None
                try:
                    for completed, entry in enumerate(plan["pages"], 1):
                        cancel_token.raise_if_cancelled()
                        if current_path != entry["path"]:
                            if source is not None:
                                source.close()
                            source = _open(snapshots[entry["path"]])
                            current_path = entry["path"]
                        with pymupdf.open() as visible:
                            page = entry["page"] - 1
                            visible.insert_pdf(
                                source,
                                from_page=page,
                                to_page=page,
                                links=False,
                                annots=True,
                                widgets=True,
                            )
                            visible.bake(annots=True, widgets=True)
                            result.insert_pdf(visible, links=False, annots=False, widgets=False)
                        result[-1].set_rotation((result[-1].rotation + entry["rotation"]) % 360)
                        progress(Progress(completed, len(plan["pages"])))
                finally:
                    if source is not None:
                        source.close()
                cancel_token.raise_if_cancelled()
                name = f"{_safe_stem(paths[0])}_organized.pdf"
                result.save(outputs.staging / name, garbage=4, deflate=True)
                for snapshot in snapshots.values():
                    snapshot.unlink()
                cancel_token.raise_if_cancelled()
                return outputs.publish([name], cancel_token)
        except OSError as exc:
            raise ConversionError(ErrorCode.OUTPUT_ERROR, "Cannot save organized PDF.") from exc
        except (RuntimeError, ValueError, OverflowError) as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"Page organization failed: {exc}"
            ) from exc


class OrganizerPreviewConverter:
    """Private worker: snapshot metadata, or one strictly bounded thumbnail at a time."""

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        import pymupdf

        cancel_token.raise_if_cancelled()
        with OutputTransaction(Path(output_dir)) as outputs:
            names = []
            if options.get("mode") == "scan":
                sources, prepared = [], {}
                total_bytes, total_pages = 0, 0
                paths = _inputs(input_path)
                for index, path in enumerate(paths):
                    cancel_token.raise_if_cancelled()
                    name = f"prepared-{uuid4().hex}.pdf"
                    info = _snapshot(
                        path,
                        outputs.staging / name,
                        cancel_token,
                        maximum_bytes=MAX_INPUT_BYTES - total_bytes,
                    )
                    total_bytes += info["size"]
                    total_pages += info["pages"]
                    if total_bytes > MAX_INPUT_BYTES or total_pages > MAX_PAGES:
                        _invalid(
                            "Combined PDFs exceed 512 MiB or 10,000 pages.", ErrorCode.INVALID_INPUT
                        )
                    sources.append(info)
                    prepared[str(path)] = name
                    names.append(name)
                    progress(Progress(index + 1, len(paths)))
                manifest = f"manifest-{uuid4().hex}.json"
                (outputs.staging / manifest).write_text(
                    json.dumps({"sources": sources, "prepared": prepared}), encoding="utf-8"
                )
                names.insert(0, manifest)
            else:
                page, rotation = options.get("page"), options.get("rotation", 0)
                if (
                    type(page) is not int
                    or not 1 <= page <= MAX_PAGES
                    or rotation not in (0, 90, 180, 270)
                ):
                    _invalid("Invalid thumbnail page or rotation.")
                with _open(Path(input_path)) as source:
                    if page > len(source):
                        _invalid("Thumbnail page is outside the source.")
                    sheet = source[page - 1]
                    sheet.set_rotation((sheet.rotation + rotation) % 360)
                    scale = THUMBNAIL_EDGE / max(sheet.rect.width, sheet.rect.height)
                    image = sheet.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
                    )
                    cancel_token.raise_if_cancelled()
                    name = f"thumb-{uuid4().hex}.png"
                    image.save(outputs.staging / name)
                    names.append(name)
            cancel_token.raise_if_cancelled()
            return outputs.publish(names, cancel_token)


def page_organizer_converters():
    return (PdfPageOrganizerConverter(),)
