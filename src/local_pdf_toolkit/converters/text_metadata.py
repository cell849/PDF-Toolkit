"""Conservative plain RTF metadata removal and explicit neutral text copying."""

import json
import re
from pathlib import Path
from uuid import uuid4

from local_pdf_toolkit.converters.metadata_package import reject, translate_errors
from local_pdf_toolkit.core.contracts import ConverterSpec, Progress
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

DROP_GROUPS = {
    "info",
    "userprops",
    "generator",
    "comment",
    "annotation",
    "atnauthor",
    "atnid",
    "atndate",
    "docvar",
    "private",
    "revtbl",
    "rsidtbl",
    "filetbl",
    "themedata",
    "colorschememapping",
    "xmlnstbl",
    "atrfstart",
    "atrfend",
    "author",
    "operator",
    "company",
    "manager",
}
ALLOWED_IGNORABLE = {"listtable", "listoverridetable", "latentstyles", "listpicture"}
UNSUPPORTED = {
    "v",
    "bin",
    "pict",
    "object",
    "objdata",
    "field",
    "datafield",
    "fontemb",
    "deleted",
    "revised",
    "revauth",
    "revdttm",
    "file",
    "htmltag",
    "htmlrtf",
}
CONTROL = re.compile(rb"\\([a-zA-Z]+)(-?[0-9]+)? ?")


def clean_rtf(data):
    if not data.startswith(b"{\\rtf"):
        reject("Not an RTF document.")

    def group(start, depth):
        if depth > 128:
            reject("RTF nesting exceeds limits.")
        header = re.match(rb"\{\s*(?:\\\*\s*)?\\([a-zA-Z]+)", data[start : start + 160])
        destination = header[1].decode("ascii") if header else ""
        ignorable = bool(re.match(rb"\{\s*\\\*", data[start : start + 30]))
        if ignorable and destination not in DROP_GROUPS | ALLOWED_IGNORABLE:
            reject("Unsupported hidden RTF destination; use a modern Office format.")
        result = bytearray(b"{")
        index = start + 1
        while index < len(data):
            byte = data[index]
            if byte == 123:
                child, index = group(index, depth + 1)
                result.extend(child)
            elif byte == 125:
                result.append(byte)
                return (b"{}" if destination in DROP_GROUPS else bytes(result)), index + 1
            elif byte == 92:
                if index + 1 >= len(data):
                    reject("Truncated RTF escape.")
                if data[index + 1] in (92, 123, 125):
                    result.extend(data[index : index + 2])
                    index += 2
                elif data[index + 1] == 39:
                    value = data[index : index + 4]
                    if len(value) != 4 or not re.fullmatch(rb"\\'[0-9a-fA-F]{2}", value):
                        reject("Invalid RTF hex escape.")
                    result.extend(value)
                    index += 4
                else:
                    match = CONTROL.match(data, index)
                    if match:
                        word = match[1].decode("ascii")
                        if word in UNSUPPORTED:
                            reject(
                                "RTF images/objects/fields and tracked changes are unsupported. "
                                "Save as DOCX first for supported cleanup."
                            )
                        if word != "rsid":
                            result.extend(match[0])
                        index = match.end()
                    else:
                        result.extend(data[index : index + 2])
                        index += 2
            else:
                result.append(byte)
                index += 1
        reject("Unbalanced RTF groups.")

    cleaned, end = group(0, 0)
    if data[end:].strip():
        reject("Unexpected data after the RTF document.")
    return cleaned


class TextMetadataConverter:
    def __init__(self, rtf=False):
        self.rtf = rtf
        self.spec = ConverterSpec(
            "metadata.clean_rtf" if rtf else "metadata.neutral_text",
            "Clean RTF metadata (basic)" if rtf else "Neutral-name text / CSV copy",
            (FileFormat.RTF,) if rtf else (FileFormat.TXT, FileFormat.CSV, FileFormat.MARKDOWN),
            (FileFormat.RTF,) if rtf else (FileFormat.TXT, FileFormat.CSV, FileFormat.MARKDOWN),
            limitations=(
                (
                    "Removes RTF Info/user properties, generator, reviewer/comment/history groups "
                    "and revision IDs. Preserves normal text and formatting. "
                    "Embedded images/objects, "
                    "fields, tracked changes and unknown hidden destinations are rejected."
                    if rtf
                    else "TXT/CSV have no standardized embedded author/GPS metadata. "
                    "This tool only "
                    "creates a neutral-name UTF-8 copy; all textual contents, "
                    "CSV comments/formulas "
                    "and Markdown frontmatter remain."
                ),
                "Visible personal content and filesystem metadata remain. "
                "This is not anonymization.",
            ),
        )

    def validate_options(self, options):
        if options:
            reject("This tool has no options.")
        return {}

    def _read(self, path):
        path = Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
            reject("Choose a regular text/RTF file below 16 MiB.")
        data = path.read_bytes()
        if len(data) > 16 * 1024 * 1024:
            reject("Text file exceeds limits.")
        return data

    def _prepare(self, path):
        data = self._read(path)
        if self.rtf:
            return FileFormat.RTF, clean_rtf(data)
        encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        text = data.decode(encoding)
        if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
            reject("Binary or unsupported text encoding.")
        suffix = Path(path).suffix.lower()
        if suffix not in (".txt", ".csv", ".md"):
            reject("Choose TXT, CSV or Markdown; content is not anonymized.")
        kind = {".txt": FileFormat.TXT, ".csv": FileFormat.CSV, ".md": FileFormat.MARKDOWN}[suffix]
        return kind, text.encode("utf-8")

    @translate_errors
    def validate_input(self, path):
        return self._prepare(path)[0]

    @translate_errors
    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        cancel_token.raise_if_cancelled()
        kind, cleaned = self._prepare(input_path)
        cancel_token.raise_if_cancelled()
        progress(Progress(1, 1))
        name = f"clean-text-{uuid4().hex[:12]}.{kind.value}"
        report_name = Path(name).stem + ".report.json"
        report = {
            "tool": self.spec.operation_id,
            "policy": "Known basic RTF metadata groups removed."
            if self.rtf
            else "Neutral filename and UTF-8 encoding only; textual data unchanged.",
            "policy_categories": ["RTF properties/reviewer/generator/history groups"]
            if self.rtf
            else ["source filename"],
            "limits": "Personal text, headers/footers, style labels, CSV formulas/comments, "
            "Markdown frontmatter and filesystem data can remain. Not anonymous.",
        }
        with OutputTransaction(Path(output_dir)) as output:
            (output.staging / name).write_bytes(cleaned)
            (output.staging / report_name).write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            return output.publish([name, report_name], cancel_token)
