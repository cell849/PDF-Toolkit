"""Desktop entry point and trusted local tool registration."""

import multiprocessing
import sys

from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.registry import ConverterRegistry


def build_registry():
    # Keep converter registration lightweight: PDF engines are loaded by the
    # operations that use them, rather than by the idle window.
    from local_pdf_toolkit.converters.compress import PdfCompressConverter
    from local_pdf_toolkit.converters.document_details import DocumentDetailsConverter
    from local_pdf_toolkit.converters.image_comparison import ImageComparisonConverter
    from local_pdf_toolkit.converters.image_metadata import ImageMetadataConverter
    from local_pdf_toolkit.converters.images import image_converters
    from local_pdf_toolkit.converters.inspector import MetadataInspector
    from local_pdf_toolkit.converters.media_metadata import media_metadata_converters
    from local_pdf_toolkit.converters.normalize_pages import PdfNormalizePagesConverter
    from local_pdf_toolkit.converters.ocr import ocr_converters
    from local_pdf_toolkit.converters.odf_metadata import OdfMetadataConverter
    from local_pdf_toolkit.converters.office_metadata import OfficeMetadataConverter
    from local_pdf_toolkit.converters.office_pdf import office_converters
    from local_pdf_toolkit.converters.page_organizer import PdfPageOrganizerConverter
    from local_pdf_toolkit.converters.pdf_compare import PdfComparisonConverter
    from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
    from local_pdf_toolkit.converters.pdf_metadata import PdfMetadataConverter
    from local_pdf_toolkit.converters.pdf_office import pdf_office_converters
    from local_pdf_toolkit.converters.pdf_tools import pdf_tool_converters
    from local_pdf_toolkit.converters.pptx_metadata import PptxMetadataConverter
    from local_pdf_toolkit.converters.redaction import redaction_converters
    from local_pdf_toolkit.converters.rename_copies import BatchRenameConverter
    from local_pdf_toolkit.converters.text_metadata import TextMetadataConverter

    registry = ConverterRegistry()
    converters = [PdfImagesConverter(fmt) for fmt in (FileFormat.JPEG, FileFormat.PNG)]
    converters.extend(image_converters())
    converters.append(ImageComparisonConverter())
    converters.append(PdfNormalizePagesConverter())
    converters.extend((PdfPageOrganizerConverter(), PdfComparisonConverter()))
    converters.extend(pdf_tool_converters())
    converters.append(PdfCompressConverter())
    converters.extend(office_converters())
    converters.extend(pdf_office_converters())
    converters.extend((ImageMetadataConverter(), PptxMetadataConverter(), PdfMetadataConverter()))
    converters.extend(
        (
            OfficeMetadataConverter(FileFormat.DOCX),
            OfficeMetadataConverter(FileFormat.XLSX),
            OdfMetadataConverter(),
            TextMetadataConverter(rtf=True),
            TextMetadataConverter(),
        )
    )
    converters.append(MetadataInspector())
    converters.extend((BatchRenameConverter(), DocumentDetailsConverter()))
    converters.extend(ocr_converters())
    converters.extend(redaction_converters())
    converters.extend(media_metadata_converters())
    for converter in converters:
        registry.register(converter)
    return registry


def main() -> int:
    multiprocessing.freeze_support()
    if "--self-test" in sys.argv:
        from local_pdf_toolkit.diagnostics import self_test

        return self_test()
    from PySide6.QtWidgets import QApplication

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LocalPDFToolkit.Desktop")
    app = QApplication(sys.argv)
    from local_pdf_toolkit.ui.icons import app_icon

    app.setWindowIcon(app_icon())
    app.setApplicationName("Local PDF Toolkit")
    app.setApplicationVersion("0.8.5")
    from local_pdf_toolkit.ui.startup import StartupScreen

    splash = StartupScreen()
    splash.show()
    app.processEvents()
    try:
        from local_pdf_toolkit.ui.main_window import MainWindow

        splash.set_stage("Preparing tools…")
        app.processEvents()
        registry = build_registry()
        splash.set_stage("Opening workspace…")
        app.processEvents()
        window = MainWindow(registry)
        window.show()
    finally:
        splash.close()
    return app.exec()
