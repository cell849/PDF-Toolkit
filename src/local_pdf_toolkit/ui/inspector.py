"""Responsive, inline settings sections for the inspector rail."""

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from local_pdf_toolkit.ui.controls import InfoButton


class PageRangeEdit(QLineEdit):
    def __init__(self, value="all"):
        super().__init__()
        self.setPlaceholderText("All pages")
        self.setText(value)

    def setText(self, value):
        super().setText("" if value.strip().lower() == "all" else value)

    def text(self):
        return super().text().strip() or "all"


class OptionLabel(QLabel):
    def __init__(self, title, explanation):
        super().__init__(title)
        self.setWordWrap(True)
        self.help = InfoButton(explanation, self)
        self.help.setAccessibleName(f"About {title}")
        self.setContentsMargins(0, 0, 30, 0)

    def heightForWidth(self, width):
        height = super().heightForWidth(width)
        if hasattr(self, "help"):
            height = max(height, self.help.sizeHint().height())
        return height

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        if hasattr(self, "help"):
            size.setHeight(max(size.height(), self.help.sizeHint().height()))
        return size

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = max(22, self.help.sizeHint().height())
        if self.contentsMargins().right() != size + 6:
            self.setContentsMargins(0, 0, size + 6, 0)
        self.help.setGeometry(max(0, self.width() - size), 0, size, size)


class InlineCheckOption(QWidget):
    """Keep a checkbox and explanation together, including at narrow widths."""

    def __init__(self, checkbox, title, explanation):
        super().__init__()
        self.setObjectName("inlineControl")
        self.checkbox = checkbox
        self.caption = OptionLabel(title, explanation)
        self.row = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.row.addWidget(checkbox)
        self.row.addWidget(self.caption, 1)

    def prepare_layout(self, width):
        minimum = (
            self.checkbox.sizeHint().width()
            + self.caption.fontMetrics().horizontalAdvance(self.caption.text())
            + self.caption.help.sizeHint().width()
            + 20
        )
        direction = (
            QBoxLayout.Direction.TopToBottom
            if width < minimum
            else QBoxLayout.Direction.LeftToRight
        )
        if self.row.direction() != direction:
            self.row.setDirection(direction)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.prepare_layout(self.width())


class FormBody(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("options")
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setVerticalSpacing(8)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self._measuring = False

    def measure(self):
        if self._measuring:
            return
        self._measuring = True
        try:
            width = max(1, self.width())
            for row in range(self.form.rowCount()):
                for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
                    item = self.form.itemAt(row, role)
                    field = item.widget() if item else None
                    if field is None or field.isHidden():
                        continue
                    if hasattr(field, "prepare_layout"):
                        field.prepare_layout(width)
                    if isinstance(field, OptionLabel):
                        # QFormLayout can otherwise allocate a wrapped label its
                        # unconstrained size hint, beyond the actual form width.
                        field.setMaximumWidth(width)
                    height = max(field.sizeHint().height(), field.minimumSizeHint().height())
                    if field.hasHeightForWidth():
                        height = max(height, field.heightForWidth(width))
                    if isinstance(field, OptionLabel):
                        height = max(height, field.help.sizeHint().height())
                    if field.minimumHeight() != height:
                        field.setMinimumHeight(height)
            self.form.invalidate()
            height = self.form.totalHeightForWidth(width)
            if height < 0:
                height = self.form.totalSizeHint().height()
            self.setMinimumHeight(height)
            # Windows can retain the old row positions after the labels gain
            # a larger minimum height. Recalculate before showing the section.
            self.form.activate()
            self.updateGeometry()
        finally:
            self._measuring = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.measure()
        # Parent scroll-area geometry can settle after this resize event.
        # Measure once more with the final width, including wrapped labels.
        QTimer.singleShot(0, self.measure)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self.measure)


class InspectorSection(QWidget):
    def __init__(self, title, body, parent=None):
        super().__init__(parent)
        self.body = body
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        self.button = QToolButton()
        self.button.setObjectName("inspectorDropdown")
        self.button.setText("  " + title)
        self.button.setCheckable(True)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.setAccessibleName(title)
        self.help = InfoButton("")
        self.help.hide()
        header.addWidget(self.button, 1)
        header.addWidget(self.help)
        layout.addLayout(header)
        self.popup = QFrame(self)
        self.popup.setObjectName("inspectorPopup")
        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(14, 14, 14, 14)
        popup_layout.addWidget(body)
        layout.addWidget(self.popup)
        self.popup.hide()
        self.button.toggled.connect(self._toggle)
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self.close)

    def open(self):
        if self.button.isEnabled():
            if self.button.isChecked():
                self._toggle(True)
            else:
                self.button.setChecked(True)

    def close(self):
        self.button.setChecked(False)

    def _toggle(self, checked):
        self.button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.popup.setVisible(checked)
        if checked:
            QTimer.singleShot(0, self.refresh)

    def refresh(self):
        if isinstance(self.body, FormBody):
            self.body.measure()
