"""Settings must be reachable without clipped fields or scrolling the inspector rail."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.design import apply_theme
from local_pdf_toolkit.ui.main_window import MainWindow


def settle(app):
    for _ in range(6):
        app.processEvents()


def test_disclosure_moves_following_section_and_tracks_width(qapp):
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    try:
        window._select_tool(
            next(
                i
                for i, spec in enumerate(window._operations)
                if spec.operation_id == "metadata.clean_pdf"
            )
        )
        settle(qapp)
        section = window.options_section
        before = window.output_section.mapTo(
            window.settings_panel, window.output_section.rect().topLeft()
        ).y()
        section.button.click()
        settle(qapp)
        after = window.output_section.mapTo(
            window.settings_panel, window.output_section.rect().topLeft()
        ).y()
        assert after > before
        assert section.popup.width() == section.width()
        assert section.button.arrowType() == Qt.ArrowType.DownArrow
        dpi = window._option_rows["dpi"][0]
        dpi.number.setValue(276)
        assert window._editors["dpi"]() == 276
        old_width = section.width()
        # Request a real width change; splitter ratios can be constrained by
        # the Windows runner's physical display at 150% scale.
        window.settings_scroll.setFixedWidth(old_width + 180)
        settle(qapp)
        assert section.width() > old_width
        assert section.popup.width() == section.width()
        section.button.click()
        settle(qapp)
        assert not section.popup.isVisible()
        assert section.button.arrowType() == Qt.ArrowType.RightArrow
        assert (
            window.output_section.mapTo(
                window.settings_panel, window.output_section.rect().topLeft()
            ).y()
            == before
        )
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        settle(qapp)


def test_unit_menu_text_remains_readable_after_theme_changes(qapp):
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    try:
        for dark in (False, True, False):
            apply_theme(window, dark)
            window._select_tool(
                next(
                    i
                    for i, spec in enumerate(window._operations)
                    if spec.operation_id == "pdf.compress"
                )
            )
            window.options_section.open()
            settle(qapp)
            choice = window._option_rows["target_value"][0].unit
            choice.setCurrentIndex(2)
            choice.showPopup()
            settle(qapp)
            view = choice.view()
            rect = view.visualRect(view.model().index(0, 0))
            image = view.viewport().grab().toImage()
            ratio = image.devicePixelRatio()
            pixels = [
                image.pixelColor(x, y).lightness()
                for x in range(int((rect.left() + 5) * ratio), int((rect.left() + 45) * ratio))
                for y in range(int((rect.top() + 4) * ratio), int((rect.bottom() - 4) * ratio))
            ]
            assert max(pixels) > 160 if dark else min(pixels) < 100
            choice.hidePopup()
            window.options_section.close()
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        settle(qapp)


def test_inspector_sections_stay_reachable_when_height_is_constrained(qapp):
    window = MainWindow(build_registry())
    window.show()
    try:
        window._select_tool(
            next(
                i for i, spec in enumerate(window._operations) if spec.operation_id == "pdf.compare"
            )
        )
        window.settings_scroll.setFixedHeight(80)
        settle(qapp)
        rail = window.settings_scroll
        assert rail.verticalScrollBar().maximum() > 0
        assert rail.verticalScrollBar().isVisible()
        rail.ensureWidgetVisible(window.output_section)
        settle(qapp)
        button = window.output_section.button
        center = button.mapTo(rail.viewport(), button.rect().center())
        assert rail.viewport().rect().contains(center)
    finally:
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        settle(qapp)


@pytest.mark.parametrize(
    "dark,width,scale", [(False, 1380, 100), (True, 760, 100), (False, 760, 200), (True, 1380, 200)]
)
def test_all_tool_dropdowns_fit_fields_and_keep_values(qapp, dark, width, scale):
    window = MainWindow(build_registry())
    window.resize(width, 720)
    window.show()
    window._set_text_size(scale)
    apply_theme(window, dark)
    try:
        for index, spec in enumerate(window._operations):
            window._select_tool(index)
            if spec.operation_id == "pdf.normalize_pages":
                paper = window._option_rows["paper"][0]
                paper.setCurrentIndex(paper.findData("custom"))
            if spec.operation_id == "pdf.compress":
                mode = window._option_rows["mode"][0]
                mode.setCurrentIndex(mode.findData("rasterized"))
            if "target_value" in window._option_rows:
                target = window._option_rows["target_value"][0]
                target.unit.setCurrentIndex(target.unit.findData("percent"))
                target.amount.setValue(60)
            original = {name: getter() for name, getter in window._editors.items()}
            settle(qapp)
            rail = window.settings_scroll
            scrollbar = rail.verticalScrollBar()
            if scale == 100:
                assert scrollbar.maximum() == 0, spec.operation_id
                assert rail.horizontalScrollBar().maximum() == 0, spec.operation_id
            elif scrollbar.maximum():
                assert scrollbar.isVisible(), spec.operation_id
                rail.ensureWidgetVisible(window.output_section)
                settle(qapp)
                button = window.output_section.button
                center = button.mapTo(rail.viewport(), button.rect().center())
                assert rail.viewport().rect().contains(center), spec.operation_id
                scrollbar.setValue(0)
            if rail.horizontalScrollBar().maximum():
                assert rail.horizontalScrollBar().isVisible(), spec.operation_id
            for section in (window.options_section, window.advanced_section):
                if section.isHidden() or not section.button.isEnabled():
                    continue
                section.open()
                settle(qapp)
                assert section.popup.isVisible()
                assert section.button.arrowType() == Qt.ArrowType.DownArrow
                assert section.popup.width() == section.width()
                previous_bottom = -1
                form = section.body.form
                for row in range(form.rowCount()):
                    label_item = form.itemAt(row, form.ItemRole.LabelRole)
                    field = form.itemAt(row, form.ItemRole.FieldRole).widget()
                    if label_item is None:
                        if not field.isHidden():
                            assert field.geometry().top() > previous_bottom
                            assert section.body.rect().contains(field.geometry())
                            previous_bottom = field.geometry().bottom()
                        continue
                    caption = label_item.widget()
                    if field.isHidden():
                        assert caption.isHidden()
                        continue
                    context = f"{spec.operation_id}: {caption.text()}, {width}px / {scale}%"
                    assert caption.geometry().top() > previous_bottom, context
                    assert field.geometry().top() > caption.geometry().bottom(), context
                    assert field.height() >= field.sizeHint().height(), context
                    assert caption.height() >= caption.heightForWidth(caption.width()), context
                    assert section.body.rect().contains(field.geometry()), context
                    for choice in (
                        [field] if isinstance(field, QComboBox) else field.findChildren(QComboBox)
                    ):
                        required = choice.fontMetrics().horizontalAdvance(choice.currentText()) + 36
                        assert choice.width() >= required, (
                            context,
                            choice.currentText(),
                            choice.width(),
                            required,
                        )
                    previous_bottom = field.geometry().bottom()
                assert {name: get() for name, get in window._editors.items()} == original
                section.button.click()
                assert not section.popup.isVisible()
                assert section.button.arrowType() == Qt.ArrowType.RightArrow
    finally:
        window.close()
        window.deleteLater()
        settle(qapp)


def test_sidebar_collapses_to_distinct_accessible_categories_and_restores(qapp):
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    try:
        window._set_sidebar_collapsed(False, remember=False)
        names = [window.navigation.item(i).text() for i in range(window.navigation.count())]
        QTest.mouseClick(window.sidebar_toggle, Qt.MouseButton.LeftButton)
        settle(qapp)
        assert window.navigation.collapsed and window.sidebar.isVisible()
        assert window.sidebar.width() == 64
        assert not window.sidebar_toggle.property("keyboardFocus")
        assert window.sidebar_toggle.width() == window.navigation.viewport().width()
        window.navigation.setFocus(Qt.FocusReason.TabFocusReason)
        window.sidebar_toggle.setFocus(Qt.FocusReason.TabFocusReason)
        assert window.sidebar_toggle.property("keyboardFocus")
        assert [window.navigation.item(i).text() for i in range(window.navigation.count())] == names
        assert all(not window.navigation.item(i).icon().isNull() for i in range(len(names)))
        images = [
            window.navigation.item(i).icon().pixmap(24, 24).toImage() for i in range(len(names))
        ]
        assert all(first != second for i, first in enumerate(images) for second in images[i + 1 :])
        item = window.navigation.item(2)
        QTest.mouseClick(
            window.navigation.viewport(),
            Qt.MouseButton.LeftButton,
            pos=window.navigation.visualItemRect(item).center(),
        )
        assert window._category == "Images"
        window.sidebar_toggle.click()
        settle(qapp)
        assert not window.navigation.collapsed and not window.sidebar_brand.isHidden()
    finally:
        window.close()
