# Third-party dependency notice

The project code is licensed under GPL-3.0-only. Third-party components have their own terms.

PyMuPDF / MuPDF: AGPL or commercial license. Review and satisfy applicable terms
before sharing source/binaries, including any corresponding source obligations.
The Windows build uses PyMuPDF 1.26.7 under AGPL-3.0; the GPL license on this
project's own code does not change the AGPL obligations for the combined app.
PyMuPDF source: https://github.com/pymupdf/PyMuPDF/tree/1.26.7
App source and build instructions: https://github.com/cell849/PDF-Toolkit
PySide6 / Qt: LGPL/GPL/commercial terms depending on components. Pillow,
python-docx, openpyxl and python-pptx have separate dependency licenses. PyInstaller
has its own license and bootloader exception. Bundled libraries can bring further
license/notice obligations; this short note is not a complete license manifest.
The bundle includes the main GNU license texts and available license files from
installed Python packages in the licenses folder. Its inventory identifies
packages whose wheels do not contain license texts. Qt source and license details:
https://doc.qt.io/qtforpython-6/licenses.html and https://www.qt.io/download-open-source

LibreOffice is separately installed and not included in the archive. Its fonts,
platform requirements, licenses and conversion behavior remain separate concerns.

Before distributing a build, inventory the bundled components and their
licenses and notices, and verify that their requirements are met. The GPL
license for this project does not replace third-party license requirements.

The optional media extra includes pillow-heif and its native HEIF/HEVC codec
libraries. Inventory the actual Windows wheel's bundled components and their
licenses before redistribution. AVIF support depends on Pillow's bundled codec.
Tesseract and FFmpeg/FFprobe are separately installed optional executables and are
not bundled or downloaded by this application.
