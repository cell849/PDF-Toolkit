"""Collect installed Python dependency license texts for the Windows bundle."""

import shutil
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

PACKAGES = (
    "PyMuPDF",
    "PySide6",
    "PySide6-Essentials",
    "PySide6-Addons",
    "shiboken6",
    "Pillow",
    "pillow-heif",
    "python-docx",
    "python-pptx",
    "openpyxl",
    "et-xmlfile",
    "lxml",
    "typing-extensions",
    "PyInstaller",
    "pyinstaller-hooks-contrib",
)


def collect(target):
    target.mkdir(parents=True, exist_ok=True)
    inventory = []
    for name in PACKAGES:
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            inventory.append(f"{name}: not installed")
            continue
        destination = target / name
        found = []
        for item in dist.files or ():
            filename = item.name.upper()
            if not any(part.endswith(".dist-info") for part in item.parts):
                continue
            if not filename.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
                continue
            source = Path(dist.locate_file(item))
            if source.is_file():
                destination.mkdir(exist_ok=True)
                shutil.copyfile(source, destination / item.name)
                found.append(item.name)
        available = ", ".join(found) or "no text in wheel metadata"
        inventory.append(f"{name} {dist.version}: {available}")
    (target / "inventory.txt").write_text("\n".join(inventory) + "\n", encoding="utf-8")


if __name__ == "__main__":
    collect(Path(sys.argv[1]))
