"""Exact keyboard entry and deliberate wheel interaction for conversion options."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QBoxLayout,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListView,
    QSlider,
    QSpinBox,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)


class _DeliberateWheel:
    """Let the surrounding settings pane scroll until this control is being edited."""

    def wheelEvent(self, event):
        explicit = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if explicit:
            super().wheelEvent(event)
        else:
            event.ignore()


class NumericSpinBox(_DeliberateWheel, QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(32)


class NumericDoubleSpinBox(_DeliberateWheel, QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(32)

    def textFromValue(self, value):
        text = super().textFromValue(value)
        separator = self.locale().decimalPoint()
        return text.rstrip("0").rstrip(separator) if separator in text else text


class ChoiceBox(_DeliberateWheel, QComboBox):
    """An app-styled list popup, including on Windows with its native window frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(32)
        self.setView(QListView())
        self.setMinimumContentsLength(6)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        # Fusion avoids platform-native combo menus that disregard the app palette.
        # Keep a Python reference: a widget does not take ownership of its style.
        self._popup_style = QStyleFactory.create("Fusion")
        self.setStyle(self._popup_style)
        self.view().setStyle(self._popup_style)
        self.view().setUniformItemSizes(True)


class _Slider(_DeliberateWheel, QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


class SliderNumber(QWidget):
    def __init__(self, minimum, maximum, value, label, suffix="", landmarks=(), parent=None):
        super().__init__(parent)
        self.setObjectName("inlineControl")
        self.landmarks = tuple(landmarks)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.slider = _Slider()
        self.slider.setRange(minimum, maximum)
        self.slider.setAccessibleName(label + " slider")
        self.slider.setMinimumHeight(28)
        self.number = NumericSpinBox()
        self.number.setRange(minimum, maximum)
        self.number.setSuffix(suffix)
        self.number.setAccessibleName(label)
        self.number.setMinimumWidth(78)
        self.number.setMaximumWidth(112)
        self.setFocusProxy(self.number)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.number)
        self.slider.valueChanged.connect(self._from_slider)
        self.number.valueChanged.connect(self._from_number)
        self.number.setValue(value)
        self._from_number(value)

    def _from_slider(self, value):
        # Only slider gestures snap. Text entry always retains the exact integer.
        if self.landmarks and self.slider.isSliderDown():
            nearest = min(self.landmarks, key=lambda mark: abs(mark - value))
            if abs(nearest - value) <= 4:
                value = nearest
        self.number.blockSignals(True)
        self.number.setValue(value)
        self.number.blockSignals(False)
        self._from_number(value)

    def _from_number(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self.slider.setToolTip(self.number.text())

    def value(self):
        return self.number.value()


class TargetSizeEditor(QWidget):
    def __init__(self, value, unit, choices, parent=None):
        super().__init__(parent)
        self.setObjectName("inlineControl")
        layout = QVBoxLayout(self)
        # The horizontal row must not impose its two-field minimum before it
        # gets a chance to stack at the scroll viewport's actual width.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        self.row = row
        row.setSpacing(8)
        self.amount = NumericDoubleSpinBox()
        self.amount.setDecimals(4)
        self.amount.setRange(0, 1_000_000)
        self.amount.setValue(value)
        self.amount.setSpecialValueText("No target")
        self.amount.setAccessibleName("Maximum file size")
        self.unit = ChoiceBox()
        self.unit.setAccessibleName("File size unit")
        for choice in choices:
            self.unit.addItem("% of original" if choice == "percent" else choice, choice)
        self.unit.setCurrentIndex(choices.index(unit))
        row.addWidget(self.amount, 1)
        row.addWidget(self.unit)
        layout.addLayout(row)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self._unit_changed()

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        # The pair may stack; its minimum width is one field, not both fields.
        if hasattr(self, "unit"):
            size.setWidth(
                max(self.amount.minimumSizeHint().width(), self.unit.minimumSizeHint().width())
            )
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        row_minimum = (
            self.amount.minimumSizeHint().width()
            + self.unit.minimumSizeHint().width()
            + self.row.spacing()
        )
        direction = (
            QBoxLayout.Direction.TopToBottom
            if self.width() < row_minimum
            else QBoxLayout.Direction.LeftToRight
        )
        if self.row.direction() != direction:
            self.row.setDirection(direction)
            self.updateGeometry()

    def _unit_changed(self, *_):
        percent = self.unit.currentData() == "percent"
        self.amount.setMaximum(100 if percent else 1_000_000)
        self.hint.setText(
            "Keep this percentage of the original file size. 0 means no target."
            if percent
            else "0 means no target. KB / MB use 1000; KiB / MiB use 1024."
        )
