"""Tiny standard-library fixture writer, independent of the production PDF engine.

Fixtures are generated from the PDF specification, contain synthetic data only, and
carry no external source or licensing requirements. Poppler supplies the test oracle.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_pdf(path, *, pages=2, rotation=0, crop=False, width=240, height=300, text_visible=True):
    objects = [b"", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids = []
    for number in range(1, pages + 1):
        page_id = len(objects) + 1
        content_id = page_id + 1
        page_ids.append(page_id)
        text_mode = 0 if text_visible else 3
        stream = (
            b"q 0.2 0.4 0.8 rg 0 0 240 300 re f Q\n"
            b"q 1 0 0 rg 25 210 100 45 re f Q\n"
            + f"BT /F1 12 Tf {text_mode} Tr 1 1 1 rg 30 230 Td (SECRET-VISIBLE) Tj ET\n".encode()
            + b"BT /F1 10 Tf 3 Tr 20 180 Td (SECRET-HIDDEN) Tj ET\n"
            + f"BT /F1 14 Tf 1 1 1 rg {text_mode} Tr 20 100 Td (PAGE-{number}) Tj ET\n".encode()
        )
        box = b" /CropBox [20 30 220 280]" if crop else b""
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
            f"/Rotate {rotation} /Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_id} 0 R".encode()
            + box
            + b" >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"endstream")
    metadata_id = len(objects) + 1
    objects.append(b"<< /Author (SECRET-AUTHOR) /Title (SECRET-TITLE) >>")
    attachment_id = len(objects) + 1
    attached = b"SECRET-ATTACHMENT"
    objects.append(
        f"<< /Type /EmbeddedFile /Length {len(attached)} >>\nstream\n".encode()
        + attached
        + b"\nendstream"
    )
    filespec_id = len(objects) + 1
    objects.append(
        f"<< /Type /Filespec /F (secret.txt) /EF << /F {attachment_id} 0 R >> >>".encode()
    )
    script_id = len(objects) + 1
    objects.append(b"<< /S /JavaScript /JS (SECRET-SCRIPT) >>")
    objects[0] = (
        f"<< /Type /Catalog /Pages 2 0 R /OpenAction {script_id} 0 R "
        f"/Names << /EmbeddedFiles << /Names [(secret.txt) {filespec_id} 0 R] >> >> >>"
    ).encode()
    kids = " ".join(f"{index} 0 R" for index in page_ids)
    objects[1] = f"<< /Type /Pages /Count {pages} /Kids [{kids}] >>".encode()
    result = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    start = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R /Info {metadata_id} 0 R >>\n"
        f"startxref\n{start}\n%%EOF\n".encode()
    )
    Path(path).write_bytes(result)
    return Path(path)


def poppler(binary, *arguments):
    executable = shutil.which(binary)
    if not executable:
        pytest.skip(f"Independent verification requires external {binary}.")
    return subprocess.run(
        [executable, *map(str, arguments)], capture_output=True, check=True, timeout=20
    ).stdout


def extract_text(path):
    return poppler("pdftotext", "-layout", path, "-").decode("utf-8")


def render(path, prefix, *, page=1):
    poppler(
        "pdftoppm",
        "-f",
        page,
        "-l",
        page,
        "-singlefile",
        "-r",
        "72",
        "-cropbox",
        "-png",
        path,
        prefix,
    )
    with Image.open(Path(prefix).with_suffix(".png")) as image:
        return image.convert("RGB")
