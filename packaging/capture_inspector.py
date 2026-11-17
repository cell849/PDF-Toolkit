"""Capture synthetic native-window evidence for inspector and unit menu review."""

from pathlib import Path

from PySide6.QtCore import QEvent, QSettings
from PySide6.QtWidgets import QApplication

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.design import apply_theme
from local_pdf_toolkit.ui.main_window import MainWindow


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(Path.cwd() / "build")
    )
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    output = Path("ui-evidence")
    output.mkdir(exist_ok=True)

    def settle():
        for _ in range(12):
            app.processEvents()

    for dark in (False, True):
        window._set_text_size(100)
        apply_theme(window, dark)
        window._select_tool(
            next(
                i
                for i, spec in enumerate(window._operations)
                if spec.operation_id == "pdf.compress"
            )
        )
        window._set_sidebar_collapsed(True, remember=False)
        settle()
        theme = "dark" if dark else "light"
        window.grab().save(str(output / f"inspector-{theme}.png"))
        window.options_section.open()
        settle()
        window.grab().save(str(output / f"inspector-open-{theme}.png"))
        window.options_section.popup.grab().save(str(output / f"options-{theme}.png"))
        unit = window._option_rows["target_value"][0].unit
        unit.showPopup()
        settle()
        unit.view().window().grab().save(str(output / f"units-{theme}.png"))
        unit.hidePopup()
        window.options_section.close()
        window._show_library()
        settle()
        window.grab().save(str(output / f"categories-{theme}.png"))
        window._browse_tools("All tools")
        settle()
        window.grab().save(str(output / f"library-{theme}.png"))
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


if __name__ == "__main__":
    main()
