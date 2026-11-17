"""Temporary, local display of selected embedded metadata values.

The saved inspection report remains masked. This reader intentionally covers only
selected PDF, image, and Office/OpenDocument properties.
"""

import json
import shutil
import subprocess
from pathlib import Path
from threading import Thread
from zipfile import BadZipFile, ZipFile

import pymupdf
from lxml import etree
from PIL import ExifTags, Image, UnidentifiedImageError
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout

_MAX_FILE = 512 * 1024 * 1024
_MAX_XML = 2 * 1024 * 1024
_PROPERTIES = {
    "creator",
    "lastModifiedBy",
    "title",
    "subject",
    "description",
    "keywords",
    "created",
    "modified",
    "Company",
    "Manager",
    "generator",
    "initial-creator",
    "creation-date",
    "date",
    "editing-duration",
    "editing-cycles",
}


def _value(value):
    """Limit displayed text and avoid dumping binary blobs."""
    if isinstance(value, bytes):
        return f"[binary data, {len(value)} bytes]"
    if isinstance(value, tuple | list):
        return ", ".join(_value(item) for item in value[:32])[:1000]
    return str(value)[:1000]


def _xml_rows(data, prefix, *, custom=False):
    """Read bounded XML without resolving entities or fetching external resources."""
    if isinstance(data, str):
        if len(data) > _MAX_XML:
            return []
        data = data.encode("utf-8")
    if not data or len(data) > _MAX_XML:
        return []
    root = etree.fromstring(
        data,
        etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False),
    )
    rows = []
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        key = node.tag.rsplit("}", 1)[-1]
        if custom and key == "property":
            name = node.get("name", "Unnamed")[:200]
            for child in node:
                if isinstance(child.tag, str) and child.text and child.text.strip():
                    rows.append((f"Custom {name}", _value(child.text.strip())))
        elif not custom and node.text and node.text.strip() and len(node) == 0:
            rows.append((f"{prefix} {key}", _value(node.text.strip())))
        if prefix == "XMP":
            for attr, value in node.attrib.items():
                name = attr.rsplit("}", 1)[-1]
                if value.strip() and name not in ("about", "parseType"):
                    rows.append((f"XMP {name}", _value(value.strip())))
        if len(rows) >= 500:
            break
    return rows[:500]


def _category(key):
    name = key.lower()
    if any(
        word in name
        for word in ("gps", "location", "latitude", "longitude", "city", "country", "sublocation")
    ):
        return "Location"
    if any(
        word in name
        for word in (
            "author",
            "artist",
            "creator",
            "owner",
            "photographer",
            "modifiedby",
            "manager",
            "company",
            "copyright",
        )
    ):
        return "Author and ownership"
    if any(word in name for word in ("date", "time", "created", "modified", "creation")):
        return "Dates and times"
    if any(
        word in name for word in ("camera", "make", "model", "lens", "device", "software", "serial")
    ):
        return "Device and software"
    if key.startswith("Custom "):
        return "Custom properties"
    return "Other properties"


_MEDIA_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".mp3",
    ".m4a",
    ".wav",
    ".flac",
    ".ogg",
    ".aac",
}


def _media_values(path):
    """Probe a local input through a pipe; keep bounded tag output in memory only."""
    from local_pdf_toolkit.converters.media_metadata import DEMUXERS, find_ffmpeg

    found = find_ffmpeg()
    probe = str(found[1]) if found else shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if not probe:
        raise ValueError("Audio/video values require a locally installed ffprobe.")
    command = [
        probe,
        "-v",
        "error",
        "-max_alloc",
        str(64 * 1024 * 1024),
        "-protocol_whitelist",
        "pipe",
        "-format_whitelist",
        DEMUXERS,
        "-show_entries",
        "format_tags:stream_tags:chapter_tags",
        "-of",
        "json",
        "pipe:0",
    ]
    chunks = []
    limit = 2 * 1024 * 1024
    with path.open("rb") as source:
        process = subprocess.Popen(
            command,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        def read_output():
            chunks.append(process.stdout.read(limit + 1))
            if len(chunks[0]) > limit:
                process.kill()

        reader = Thread(target=read_output, daemon=True)
        reader.start()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise ValueError("Audio/video metadata reading timed out.") from exc
        finally:
            reader.join()
            process.stdout.close()
        if process.returncode or not chunks or len(chunks[0]) > limit:
            raise ValueError("Cannot read supported audio/video metadata.")
    try:
        info = json.loads(chunks[0])
        rows = []
        for label, items in (
            ("Media", [info.get("format", {})]),
            ("Media stream", info.get("streams", [])),
            ("Media chapter", info.get("chapters", [])),
        ):
            for index, item in enumerate(items[:128], 1):
                for key, value in item.get("tags", {}).items():
                    if isinstance(key, str) and isinstance(value, str):
                        suffix = f" {index}" if label != "Media" else ""
                        rows.append((f"{label}{suffix} {key[:200]}", _value(value)))
                        if len(rows) >= 500:
                            return rows
        return rows
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Cannot parse audio/video metadata.") from exc


def metadata_values(path):
    """Return selected human-readable fields; never write values to disk."""
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= _MAX_FILE:
        raise ValueError("Choose a regular file below 512 MiB.")
    with path.open("rb") as stream:
        header = stream.read(1024)
    rows = []
    if header.lstrip().startswith(b"%PDF-"):
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise ValueError("This PDF requires a password.")
            for key, value in (doc.metadata or {}).items():
                if value and key not in ("format", "encryption"):
                    rows.append((f"PDF {key}", _value(value)))
            xmp = doc.get_xml_metadata()
            if xmp:
                try:
                    rows.extend(_xml_rows(xmp, "XMP"))
                except etree.XMLSyntaxError:
                    pass
    elif header.startswith(b"PK"):
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 20_000 or sum(entry.file_size for entry in entries) > _MAX_FILE:
                raise ValueError("Office package exceeds inspection limits.")
            for name in (
                "docProps/core.xml",
                "docProps/app.xml",
                "docProps/custom.xml",
                "meta.xml",
            ):
                matches = [entry for entry in entries if entry.filename == name]
                if len(matches) > 1:
                    raise ValueError("Duplicate metadata parts are unsupported.")
                if not matches:
                    continue
                entry = matches[0]
                if entry.flag_bits & 1 or entry.file_size > _MAX_XML:
                    raise ValueError("Metadata part is encrypted or too large.")
                data = archive.read(entry)
                if name == "docProps/custom.xml":
                    rows.extend(_xml_rows(data, "Custom", custom=True))
                    continue
                root = etree.fromstring(
                    data,
                    etree.XMLParser(
                        resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False
                    ),
                )
                for node in root.iter():
                    if not isinstance(node.tag, str):
                        continue
                    key = node.tag.rsplit("}", 1)[-1]
                    if key in _PROPERTIES and node.text and node.text.strip():
                        rows.append((f"Document {key}", _value(node.text.strip())))
    elif path.suffix.lower() in _MEDIA_SUFFIXES:
        rows.extend(_media_values(path))
    else:
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                for tag in exif:
                    name = ExifTags.TAGS.get(tag, f"Tag {tag}")
                    if tag == 34853:  # GPSInfo is an offset; resolve its nested fields.
                        gps = exif.get_ifd(tag)
                        for gps_tag, value in gps.items():
                            label = ExifTags.GPSTAGS.get(gps_tag, f"Tag {gps_tag}")
                            rows.append((f"GPS {label}", _value(value)))
                    elif tag not in (34665, 40965):
                        rows.append((f"EXIF {name}", _value(exif[tag])))
                for tag, value in exif.get_ifd(34665).items():
                    rows.append((f"EXIF {ExifTags.TAGS.get(tag, f'Tag {tag}')}", _value(value)))
                xmp = image.info.get("xmp") or image.info.get("XML:com.adobe.xmp")
                if isinstance(xmp, str | bytes):
                    try:
                        rows.extend(_xml_rows(xmp, "XMP"))
                    except etree.XMLSyntaxError:
                        pass
                for key, value in getattr(image, "text", {}).items():
                    rows.append((f"Image text {str(key)[:200]}", _value(value)))
        except UnidentifiedImageError:
            return []
    return rows[:500]


class _Signals(QObject):
    finished = Signal(object)


class _Reader(QRunnable):
    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self.signals = _Signals()

    def run(self):
        sections = []
        for index, path in enumerate(self.paths, 1):
            try:
                rows = metadata_values(path)
                lines = []
                for category in (
                    "Author and ownership",
                    "Location",
                    "Device and software",
                    "Dates and times",
                    "Custom properties",
                    "Other properties",
                ):
                    group = [f"{key}: {value}" for key, value in rows if _category(key) == category]
                    if group:
                        lines.extend([f"[{category}]", *group])
                if not lines:
                    lines = [
                        "No supported values found, or this format is not covered "
                        "by the value viewer."
                    ]
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                BadZipFile,
                etree.XMLSyntaxError,
                RuntimeError,
                EOFError,
                OverflowError,
                Image.DecompressionBombError,
            ):
                detail = (
                    " Audio/video requires locally installed ffprobe."
                    if Path(path).suffix.lower() in _MEDIA_SUFFIXES
                    else ""
                )
                lines = ["Could not read supported values from this file." + detail]
            suffix = Path(path).suffix.lower()
            if suffix == ".pdf":
                coverage = (
                    "PDF properties and XMP; attachments and other metadata are not inspected."
                )
            elif suffix in _MEDIA_SUFFIXES:
                coverage = (
                    "Selected container, stream and chapter tags via ffprobe; "
                    "other data may remain."
                )
            elif suffix in {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}:
                coverage = (
                    "Document and custom properties; embedded content and other metadata "
                    "are not inspected."
                )
            else:
                coverage = (
                    "Selected image EXIF, GPS, text and XMP; other formats or metadata "
                    "may not be covered."
                )
            sections.append(
                f"FILE {index}: {Path(path).name}\nCoverage: {coverage}\n" + "\n".join(lines)
            )
        try:
            self.signals.finished.emit("\n\n".join(sections))
        except RuntimeError:
            pass  # The dialog was closed before the read completed.


class MetadataValuesDialog(QDialog):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadata values")
        self.resize(700, 500)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Values are shown locally and may contain private information. "
            "Files are read again when this view opens. "
            "Coverage: selected PDF properties and XMP, image EXIF, GPS, text and XMP, "
            "and Office/OpenDocument properties including Office custom properties. "
            "Audio/video container, stream and chapter tags require local ffprobe; "
            "some media may not be readable through its offline input. "
            "Other formats and metadata may be missing or truncated. "
            "The saved report contains counts only."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search displayed metadata")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self._contents = ""
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText("Reading metadata…")
        layout.addWidget(self.text)
        self._reader = _Reader(tuple(paths))
        self._reader.signals.finished.connect(self._set_contents)
        QThreadPool.globalInstance().start(self._reader)

    def _set_contents(self, contents):
        self._contents = contents
        self._filter(self.search.text())

    def _filter(self, query):
        if not self._contents:
            return
        if not query.strip():
            self.text.setPlainText(self._contents)
            return
        needle = query.casefold().strip()
        sections = self._contents.split("\n\n")
        matches = []
        for section in sections:
            lines = section.splitlines()
            found = [line for line in lines[1:] if needle in line.casefold()]
            if found or (lines and needle in lines[0].casefold()):
                matches.append("\n".join([lines[0], *(found or lines[1:])]))
        self.text.setPlainText("\n\n".join(matches) or "No matching displayed values.")
