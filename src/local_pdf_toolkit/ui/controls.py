"""Compact native controls with exact keyboard entry and optional slider landmarks."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class SliderNumber(QWidget):
    def __init__(self, minimum, maximum, value, label, suffix="", landmarks=(), parent=None):
        super().__init__(parent)
        self.setObjectName("inlineControl")
        self.landmarks = tuple(landmarks)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setAccessibleName(label + " slider")
        self.slider.setMinimumHeight(28)
        self.number = QSpinBox()
        self.number.setRange(minimum, maximum)
        self.number.setSuffix(suffix)
        self.number.setAccessibleName(label)
        self.number.setMinimumWidth(100)
        self.number.setMinimumHeight(28)
        self.setFocusProxy(self.number)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.number)
        self.slider.valueChanged.connect(self._from_slider)
        self.number.valueChanged.connect(self._from_number)
        self.number.setValue(value)
        self._from_number(value)

    def _from_slider(self, value):
        # Only slider gestures snap. Text entry always retains the exact integer.
        if self.landmarks:
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.amount = QDoubleSpinBox()
        self.amount.setDecimals(4)
        self.amount.setRange(0, 1_000_000)
        self.amount.setValue(value)
        self.amount.setSpecialValueText("No target")
        self.amount.setAccessibleName("Maximum file size")
        self.amount.setMinimumHeight(28)
        self.unit = QComboBox()
        self.unit.setAccessibleName("File size unit")
        for choice in choices:
            self.unit.addItem("% of original" if choice == "percent" else choice, choice)
        self.unit.setCurrentIndex(choices.index(unit))
        self.unit.setMinimumHeight(28)
        row.addWidget(self.amount, 1)
        row.addWidget(self.unit)
        layout.addLayout(row)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self._unit_changed()

    def _unit_changed(self, *_):
        percent = self.unit.currentData() == "percent"
        self.amount.setMaximum(100 if percent else 1_000_000)
        self.hint.setText(
            "Keep this percentage of the original file size. 0 means no target."
            if percent
            else "0 means no target. KB / MB use 1000; KiB / MiB use 1024."
        )
