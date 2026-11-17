"""Exact keyboard entry and deliberate wheel interaction for conversion options."""

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainterPath, QPalette, QRegion
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QBoxLayout,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QListView,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyleFactory,
    QToolButton,
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
        self.view().window().setObjectName("choicePopup")
        self.currentIndexChanged.connect(self._fit_current_text)

    def _fit_current_text(self, *_):
        self.setMinimumWidth(self.fontMetrics().horizontalAdvance(self.currentText()) + 44)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._fit_current_text()

    def showPopup(self):
        # The private popup is a separate window; it does not reliably inherit
        # a parent window's palette or stylesheet on Windows/Fusion.
        palette = self.palette()
        base = palette.color(QPalette.ColorRole.Base).name()
        text = palette.color(QPalette.ColorRole.Text).name()
        selected = palette.color(QPalette.ColorRole.Highlight).name()
        frame = palette.color(QPalette.ColorRole.Mid).name()
        popup = self.view().window()
        popup.setObjectName("choicePopup")
        popup.setPalette(palette)
        popup.setFont(self.font())
        self.view().setPalette(palette)
        self.view().setFont(self.font())
        self.view().setStyleSheet(f"""
            QListView {{ background: {base}; color: {text}; border: 0; padding: 4px;
                outline: none; font-size: {self.font().pointSizeF()}pt; }}
            QListView::item {{ padding: 6px 10px; border-radius: 6px; color: {text}; }}
            QListView::item:selected, QListView::item:hover {{
                background: {selected}; color: {text}; }}
        """)
        popup.setStyleSheet(f"""
            QFrame#choicePopup {{ background: {base}; color: {text};
                border: 1px solid {frame}; border-radius: 8px; padding: 3px; }}
        """)
        super().showPopup()
        # The popup is a separate native window on Windows. Clip that window,
        # rather than just its list, so its corners follow the rounded frame.
        popup = self.view().window()
        path = QPainterPath()
        path.addRoundedRect(QRectF(popup.rect()), 8, 8)
        popup.setMask(QRegion(path.toFillPolygon().toPolygon()))


class _Slider(_DeliberateWheel, QSlider):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


class SliderNumber(QWidget):
    valueChanged = Signal(int)

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
        self.valueChanged.emit(value)

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
        self.hint.hide()
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
        self.prepare_layout(self.width())

    def prepare_layout(self, width):
        self.unit.setMinimumWidth(
            self.unit.fontMetrics().horizontalAdvance(self.unit.currentText()) + 44
        )
        row_minimum = (
            self.amount.minimumSizeHint().width()
            + max(self.unit.minimumSizeHint().width(), self.unit.minimumWidth())
            + self.row.spacing()
        )
        direction = (
            QBoxLayout.Direction.TopToBottom
            if width < row_minimum
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
        self.amount.setToolTip(self.hint.text())
        self.unit.setToolTip(self.hint.text())
        self.prepare_layout(self.width())


class InfoButton(QToolButton):
    """A compact, keyboard-accessible explanation for a nearby setting."""

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setObjectName("infoButton")
        self.setText("i")
        self.setToolTip(text)
        self.setAccessibleName("More information")
        self.setAccessibleDescription(text)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._help_text = text
        self._popover = None
        self.clicked.connect(self._show_help)

    def sizeHint(self):
        side = max(24, self.fontMetrics().height() + 6)
        return QSize(side, side)

    def minimumSizeHint(self):
        return self.sizeHint()

    def set_help_text(self, text):
        self._help_text = text
        self.setToolTip(text)
        self.setAccessibleDescription(text)
        if self._popover is not None:
            self._help_label.setText(text)

    def _show_help(self):
        if self._popover is None:
            popup = QFrame(self, Qt.WindowType.Popup)
            popup.setObjectName("infoPopover")
            layout = QVBoxLayout(popup)
            layout.setContentsMargins(12, 12, 12, 12)
            scroll = QScrollArea()
            scroll.setObjectName("helpScroll")
            scroll.viewport().setObjectName("helpViewport")
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            label = QLabel(self._help_text)
            label.setObjectName("helpText")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            scroll.setWidget(label)
            layout.addWidget(scroll)
            self._help_label = label
            self._popover = popup
        screen = self.screen().availableGeometry()
        width = min(max(360, self.fontMetrics().height() * 22), screen.width() - 24)
        height = self._help_label.heightForWidth(width - 38) + 32
        self._help_label.setMinimumHeight(height - 32)
        self._popover.resize(width, min(height, screen.height() - 40))
        point = self.mapToGlobal(QPoint(0, self.height() + 4))
        self._popover.move(
            min(max(screen.left() + 8, point.x()), screen.right() - width - 8),
            min(max(screen.top() + 8, point.y()), screen.bottom() - self._popover.height() - 8),
        )
        self._popover.show()
