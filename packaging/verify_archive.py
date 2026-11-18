"""Check the files and checksum of the distributable Windows ZIP."""

import hashlib
import sys
import zipfile
from pathlib import Path


def verify(path):
    path = Path(path)
    expected = path.with_name(path.name + ".sha256").read_text(encoding="ascii").split()[0]
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("Windows archive checksum does not match")
    with zipfile.ZipFile(path) as archive:
        for name in ("PDFToolkit/PDFToolkit.exe", "PDFToolkit/LICENSE.txt"):
            if archive.getinfo(name).file_size == 0:
                raise ValueError(f"Empty required archive file: {name}")
        agpl = archive.read("PDFToolkit/licenses/AGPL-3.0.txt")
        if b"GNU AFFERO GENERAL PUBLIC LICENSE" not in agpl or len(agpl) < 30000:
            raise ValueError("The archive does not contain the full AGPL license text")


if __name__ == "__main__":
    verify(sys.argv[1])
