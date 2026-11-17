"""User-visible layout checks for the compact desktop workspace."""

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QProgressBar

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow
from local_pdf_toolkit.ui.shell import CATEGORIES


def settle(app):
    for _ in range(10):
        app.processEvents()


def close_widget(widget, app):
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    settle(app)


def test_all_categories_align_card_text_when_it_fits(qapp):
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    try:
        for category in CATEGORIES:
            window._browse_tools(category)
            settle(qapp)
            for row in range(window.library.grid.rowCount()):
                cards = [
                    window.library.grid.itemAtPosition(row, col).widget()
                    for col in range(window.library.columns)
                    if window.library.grid.itemAtPosition(row, col)
                ]
                if not cards:
                    continue
                assert len({card.layout().itemAt(1).widget().y() for card in cards}) == 1
                short = [
                    card
                    for card in cards
                    if card.layout()
                    .itemAt(1)
                    .widget()
                    .fontMetrics()
                    .horizontalAdvance(card.layout().itemAt(1).widget().text())
                    <= card.layout().itemAt(1).widget().width()
                ]
                assert len({card.layout().itemAt(2).widget().y() for card in short}) <= 1
    finally:
        close_widget(window, qapp)


def test_units_and_checkbox_stay_inline_when_space_is_available(qapp):
    from local_pdf_toolkit.ui.inspector import InlineCheckOption

    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    try:
        window._select_tool(
            next(
                i
                for i, spec in enumerate(window._operations)
                if spec.operation_id == "image.to_jpeg"
            )
        )
        window.options_section.open()
        settle(qapp)
        for key in ("width", "height"):
            _, caption = window._option_rows[key]
            text_width = caption.fontMetrics().horizontalAdvance(caption.text())
            assert caption.width() >= text_width + caption.help.width()
            assert caption.help.x() >= text_width
            assert (
                caption.height() <= max(caption.fontMetrics().height(), caption.help.height()) + 2
            )
        window._select_tool(
            next(
                i for i, spec in enumerate(window._operations) if spec.operation_id == "pdf.to_png"
            )
        )
        window.advanced_section.open()
        settle(qapp)
        option, _ = window._option_rows["alpha"]
        assert isinstance(option, InlineCheckOption)
        assert option.checkbox.geometry().center().y() == option.caption.geometry().center().y()
        assert not window._editors["alpha"]()
        QTest.mouseClick(option.checkbox, Qt.MouseButton.LeftButton)
        assert window._editors["alpha"]()
    finally:
        close_widget(window, qapp)


def test_all_boolean_options_preserve_their_values(qapp):
    from local_pdf_toolkit.ui.inspector import InlineCheckOption

    window = MainWindow(build_registry())
    try:
        for index, spec in enumerate(window._operations):
            window._select_tool(index)
            for option in spec.options:
                if not isinstance(option.default, bool):
                    continue
                editor, _ = window._option_rows[option.name]
                assert isinstance(editor, InlineCheckOption), (spec.operation_id, option.name)
                editor.checkbox.setChecked(not option.default)
                assert window._editors[option.name]() is not option.default
    finally:
        close_widget(window, qapp)


def test_scrollbars_remain_at_outer_edge_with_clearance(qapp):
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    try:
        window._browse_tools("All tools")
        settle(qapp)
        library = window.library_scroll
        assert library.verticalScrollBar().isVisible()
        assert window.library.grid.contentsMargins().right() >= 16
        window._select_tool(
            next(
                i
                for i, spec in enumerate(window._operations)
                if spec.operation_id == "pdf.normalize_pages"
            )
        )
        window.options_section.open()
        window.output_section.open()
        window.settings_scroll.setFixedHeight(200)
        settle(qapp)
        settings = window.settings_scroll
        assert settings.verticalScrollBar().isVisible()
        assert window.settings_panel.layout().contentsMargins().right() >= 16
        for scroll in (library, settings):
            bar = scroll.verticalScrollBar()
            pos = bar.mapTo(scroll, QPoint(0, 0))
            assert abs((pos.x() + bar.width()) - scroll.width()) <= 2
    finally:
        close_widget(window, qapp)


def test_startup_screen_is_minimal_and_indeterminate(qapp):
    from local_pdf_toolkit.ui.startup import StartupScreen

    splash = StartupScreen()
    splash.show()
    try:
        settle(qapp)
        labels = splash.findChildren(QLabel)
        assert any(label.text() == "Local PDF Toolkit" for label in labels)
        assert any(label.pixmap() and not label.pixmap().isNull() for label in labels)
        progress = splash.findChild(QProgressBar)
        assert (progress.minimum(), progress.maximum()) == (0, 0)
    finally:
        close_widget(splash, qapp)
