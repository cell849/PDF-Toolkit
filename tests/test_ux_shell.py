"""Workspace structure, intentional numeric entry, and packaged identity."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QIcon, QWheelEvent
from PySide6.QtWidgets import QAbstractSpinBox, QLabel, QListView, QWidget

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.controls import ChoiceBox, NumericDoubleSpinBox, NumericSpinBox
from local_pdf_toolkit.ui.design import DARK, LIGHT, apply_theme
from local_pdf_toolkit.ui.icons import app_icon, resource_path
from local_pdf_toolkit.ui.main_window import MainWindow
from local_pdf_toolkit.ui.shell import matches_search


def wheel(widget, modifiers=Qt.KeyboardModifier.NoModifier):
    event = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    widget.wheelEvent(event)
    return event


def test_numbers_require_deliberate_wheel_and_keep_keyboard_step_support(qapp):
    for cls in (NumericSpinBox, NumericDoubleSpinBox):
        number = cls()
        try:
            number.setRange(0, 100)
            number.setValue(25)
            assert number.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
            assert not number.hasFocus()
            event = wheel(number)
            assert number.value() == 25
            assert not event.isAccepted()
            wheel(number, Qt.KeyboardModifier.ControlModifier)
            assert number.value() > 25
            number.setValue(25)
            number.stepUp()
            assert number.value() == 26
            number.stepDown()
            assert number.value() == 25
        finally:
            number.close()


def test_choice_popup_uses_the_same_list_and_deliberate_wheel(qapp):
    choice = ChoiceBox()
    try:
        choice.addItems(("KB", "MB", "% of original"))
        choice.setCurrentIndex(1)
        assert isinstance(choice.view(), QListView)
        assert choice.style().objectName().lower() == "fusion"
        wheel(choice)
        assert choice.currentIndex() == 1
        wheel(choice, Qt.KeyboardModifier.ControlModifier)
        assert choice.currentIndex() == 0
    finally:
        choice.close()


def test_workspace_keeps_result_feedback_and_options_reachable(qapp):
    window = MainWindow(build_registry())
    try:
        index = next(
            i for i, spec in enumerate(window._operations) if spec.operation_id == "image.to_jpeg"
        )
        window._select_tool(index)
        window.show()
        qapp.processEvents()
        assert window.workspace_splitter.count() == 3
        assert window.workspace_splitter.widget(1) is window.preview_host
        assert window.workspace_splitter.widget(2) is window.settings_scroll
        assert window.preview_host.layout() is not None
        assert window.result_banner.isVisible()
        assert window.summary.isVisible()
        assert window.compare_button is window.result_compare
        assert window.retry_button is window.result_retry
        window.resize(760, 620)
        qapp.processEvents()
        assert window.result_title.isVisible()
        window.settings_action.setChecked(False)
        assert not window.settings_scroll.isVisible()
        window.settings_action.setChecked(True)
        assert window.settings_scroll.isVisible()
        window.result_adjust.click()
        assert window.settings_action.isChecked()
        assert window.result_title.geometry().height() > 0
        actions = [
            action.text()
            for menu in window.menuBar().findChildren(QWidget)
            if hasattr(menu, "actions")
            for action in menu.actions()
        ]
        assert "Paste files" in actions
        assert "Undo file change" in actions
        assert "Tool availability…" in actions
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_task_search_matches_aliases_and_all_tokens(qapp):
    operations = {spec.operation_id: spec for spec in build_registry().list_operations()}
    assert matches_search(operations["pdf.merge"], "join pdf")
    assert matches_search(operations["image.to_jpeg"], "shrink photo")
    assert not matches_search(operations["pdf.merge"], "join impossible")


@pytest.mark.parametrize("dark", (False, True))
@pytest.mark.parametrize("width", (760, 1636))
def test_library_cards_keep_all_text_visible_after_theme_and_text_changes(qapp, dark, width):
    window = MainWindow(build_registry())
    window.resize(width, 860)
    window.show()
    try:
        for percent in (100, 200, 100):
            window._set_text_size(percent)
            apply_theme(window, dark)
            # Font and wrapping changes post nested layout requests.
            for _ in range(8):
                qapp.processEvents()
            for card in window.library.cards:
                assert card.isVisible() and card.height() >= 164
                for text in card.findChildren(QLabel):
                    assert text.isVisible() and text.width() > 0
                    assert text.height() >= text.heightForWidth(text.width())
                    assert card.rect().contains(text.geometry())
            for index, first in enumerate(window.library.cards):
                for second in window.library.cards[index + 1 :]:
                    assert not first.geometry().intersects(second.geometry())
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def contrast(a, b):
    def luminance(color):
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_text_tokens_meet_contrast_and_icon_contains_windows_sizes(qapp):
    for colors in (LIGHT, DARK):
        for text_role in ("text", "secondary", "accent"):
            assert contrast(colors[text_role], colors["surface"]) >= 4.5
        assert contrast(colors["primary_text"], colors["accent"]) >= 4.5
    assert resource_path("app.svg").is_file()
    assert resource_path("app.png").is_file()
    icon = app_icon()
    assert not icon.isNull()
    assert isinstance(icon, QIcon)
    assert {16, 32, 48, 256} <= {size.width() for size in icon.availableSizes()}


def test_focused_number_does_not_change_when_scrolling_settings(qapp):
    number = NumericSpinBox()
    number.setRange(0, 1200)
    number.setValue(276)
    number.show()
    number.setFocus()
    qapp.processEvents()
    wheel(number)
    assert number.value() == 276
    number.close()


def test_fractional_amount_keeps_precision_without_padding_zeroes(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    number = NumericDoubleSpinBox()
    number.setRange(0, 1000)
    number.setDecimals(4)
    number.setValue(2)
    assert number.text() == "2"
    number.show()
    number.selectAll()
    QTest.keyClicks(number, "2.1250")
    QTest.keyClick(number, Qt.Key.Key_Return)
    assert number.value() == 2.125
    assert number.text() == "2.125"
    number.close()
