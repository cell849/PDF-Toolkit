"""Control interactions that should survive styling and larger text."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QBoxLayout, QCheckBox, QLabel, QVBoxLayout, QWidget

from local_pdf_toolkit.ui.controls import InfoButton, SliderNumber, TargetSizeEditor
from local_pdf_toolkit.ui.design import apply_theme


def test_help_is_available_from_keyboard_and_keeps_full_text(qapp):
    text = "A detailed explanation of this setting. " * 12
    window = QWidget()
    layout = QVBoxLayout(window)
    button = InfoButton(text)
    layout.addWidget(button)
    apply_theme(window)
    window.show()
    button.setFocus()
    QTest.keyClick(button, Qt.Key.Key_Space)
    qapp.processEvents()
    try:
        assert button.toolTip() == text
        assert button.accessibleDescription() == text
        assert button._popover.isVisible()
        label = button._popover.findChild(QLabel)
        assert label.text() == text
        assert label.wordWrap()
        assert label.height() >= label.heightForWidth(label.width())
        QTest.keyClick(button._popover, Qt.Key.Key_Escape)
        assert not button._popover.isVisible()
    finally:
        window.close()


def test_large_text_controls_keep_exact_value_and_target_help(qapp):
    window = QWidget()
    window.setProperty("textScale", 2.0)
    layout = QVBoxLayout(window)
    slider = SliderNumber(10, 1200, 300, "Resolution", suffix=" dpi", landmarks=(300,))
    target = TargetSizeEditor(0, "MB", ["MB", "percent"])
    layout.addWidget(slider)
    layout.addWidget(target)
    apply_theme(window)
    window.resize(650, 300)
    window.show()
    qapp.processEvents()
    try:
        slider.number.setFocus()
        slider.number.selectAll()
        QTest.keyClicks(slider.number, "298")
        QTest.keyClick(slider.number, Qt.Key.Key_Return)
        assert slider.value() == slider.slider.value() == 298
        assert slider.number.height() >= slider.number.fontMetrics().height()
        assert target.unit.height() >= target.unit.fontMetrics().height()
        assert target.hint.isHidden()
        target.unit.setCurrentIndex(target.unit.findData("percent"))
        assert "Keep this percentage" in target.amount.toolTip()
    finally:
        window.close()


def test_resolution_reduction_checkbox_adapts_to_available_width(qapp):
    from local_pdf_toolkit.ui.inspector import InlineCheckOption

    checkbox = QCheckBox()
    option = InlineCheckOption(checkbox, "Allow smaller dimensions", "May reduce resolution")
    option.show()
    try:
        option.resize(500, 80)
        qapp.processEvents()
        assert option.row.direction() == QBoxLayout.Direction.LeftToRight
        checkbox.setChecked(True)
        option.resize(100, 120)
        qapp.processEvents()
        assert option.row.direction() == QBoxLayout.Direction.TopToBottom
        assert checkbox.isChecked()
    finally:
        option.close()


def test_open_choice_menu_inherits_dark_palette_and_keeps_keyboard_selection(qapp):
    from PySide6.QtGui import QPalette

    from local_pdf_toolkit.ui.controls import ChoiceBox

    window = QWidget()
    layout = QVBoxLayout(window)
    choice = ChoiceBox()
    choice.addItem("Portrait", "portrait")
    choice.addItem("Landscape", "landscape")
    choice.addItem("Auto", "auto")
    layout.addWidget(choice)
    apply_theme(window, True)
    window.show()
    choice.showPopup()
    qapp.processEvents()
    try:
        assert choice.view().palette().color(QPalette.ColorRole.Base) == choice.palette().color(
            QPalette.ColorRole.Base
        )
        assert choice.view().font().pointSizeF() == choice.font().pointSizeF()
        assert choice.view().sizeHintForRow(0) >= choice.fontMetrics().height() + 10
        QTest.keyClick(choice.view(), Qt.Key.Key_Down)
        QTest.keyClick(choice.view(), Qt.Key.Key_Return)
        assert choice.currentData() == "landscape"
    finally:
        choice.hidePopup()
        window.close()
