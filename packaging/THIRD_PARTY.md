# Third-party dependency notice

The project code is MIT-licensed. Third-party components have their own terms.

PyMuPDF / MuPDF: AGPL or commercial license. Review and satisfy applicable terms
before sharing source/binaries, including any corresponding source obligations.
PySide6 / Qt: LGPL/GPL/commercial terms depending on components. Pillow,
python-docx, openpyxl and python-pptx have separate dependency licenses. PyInstaller
has its own license and bootloader exception. Bundled libraries can bring further
license/notice obligations; this short note is not a complete license manifest.

LibreOffice is separately installed and not included in the archive. Its fonts,
platform requirements, licenses and conversion behavior remain separate concerns.

Before distributing a build, inventory the bundled components and their
licenses and notices, and verify that their requirements are met. The MIT
license for this project does not replace third-party license requirements.

The optional media extra includes pillow-heif and its native HEIF/HEVC codec
libraries. Inventory the actual Windows wheel's bundled components and their
licenses before redistribution. AVIF support depends on Pillow's bundled codec.
Tesseract and FFmpeg/FFprobe are separately installed optional executables and are
not bundled or downloaded by this application.
