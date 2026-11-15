"""Desktop entry point with the M1 PDF-to-image adapters."""

import multiprocessing
import sys

from PySide6.QtWidgets import QApplication

from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.registry import ConverterRegistry
from local_pdf_toolkit.ui.main_window import MainWindow


def build_registry():
    from local_pdf_toolkit.converters.compress import PdfCompressConverter
    from local_pdf_toolkit.converters.images import image_converters
    from local_pdf_toolkit.converters.office_pdf import office_converters
    from local_pdf_toolkit.converters.pdf_office import pdf_office_converters
    from local_pdf_toolkit.converters.pdf_tools import pdf_tool_converters

    registry = ConverterRegistry()
    converters = [PdfImagesConverter(fmt) for fmt in (FileFormat.JPEG, FileFormat.PNG)]
    converters.extend(image_converters())
    converters.extend(pdf_tool_converters())
    converters.append(PdfCompressConverter())
    converters.extend(office_converters())
    converters.extend(pdf_office_converters())
    for converter in converters:
        registry.register(converter)
    return registry


def main() -> int:
    multiprocessing.freeze_support()
    if "--self-test" in sys.argv:
        from local_pdf_toolkit.diagnostics import self_test

        return self_test()
    app = QApplication(sys.argv)
    app.setApplicationName("Local PDF Toolkit")
    app.setApplicationVersion("0.3.0")
    window = MainWindow(build_registry())
    window.show()
    return app.exec()
