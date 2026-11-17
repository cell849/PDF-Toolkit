"""Anchored, content-sized settings sections; the inspector rail never scrolls."""

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = max(22, self.help.sizeHint().height())
        if self.contentsMargins().right() != size + 6:
            self.setContentsMargins(0, 0, size + 6, 0)
        self.help.setGeometry(max(0, self.width() - size), 0, size, size)


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
        finally:
            self._measuring = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.measure()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self.measure)


class _Popup(QFrame):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Popup)
        self.owner = owner
        self.setObjectName("inspectorPopup")

    def hideEvent(self, event):
        super().hideEvent(event)
        self.owner.button.blockSignals(True)
        self.owner.button.setChecked(False)
        self.owner.button.blockSignals(False)


class InspectorSection(QWidget):
    def __init__(self, title, body, parent=None):
        super().__init__(parent)
        self.body = body
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.button = QToolButton()
        self.button.setObjectName("inspectorDropdown")
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setArrowType(Qt.ArrowType.DownArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.setAccessibleName(title)
        self.help = InfoButton("")
        self.help.hide()
        layout.addWidget(self.button, 1)
        layout.addWidget(self.help)
        self.popup = _Popup(self)
        popup_layout = QVBoxLayout(self.popup)
        popup_layout.setContentsMargins(14, 14, 14, 14)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("inspectorScroll")
        self.scroll.viewport().setObjectName("inspectorViewport")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(body)
        popup_layout.addWidget(self.scroll)
        self.button.toggled.connect(self._toggle)

    def open(self):
        if self.button.isEnabled():
            if self.button.isChecked():
                self._toggle(True)
            else:
                self.button.setChecked(True)

    def close(self):
        self.popup.hide()

    def _toggle(self, checked):
        if not checked:
            self.popup.hide()
            return
        was_visible = self.popup.isVisible()
        screen = self.screen().availableGeometry()
        preferred = 340
        for choice in self.body.findChildren(QComboBox):
            metrics = choice.fontMetrics()
            preferred = max(
                preferred,
                max(
                    (metrics.horizontalAdvance(choice.itemText(i)) for i in range(choice.count())),
                    default=0,
                )
                + 90,
            )
        preferred = max(preferred, self.body.minimumSizeHint().width() + 44)
        width = min(preferred, screen.width() - 24)
        self.body.resize(width - 44, self.body.height())
        if isinstance(self.body, FormBody):
            self.body.measure()
        self.body.layout().activate()
        desired = max(self.body.minimumHeight(), self.body.sizeHint().height()) + 32
        height = min(desired, screen.height() - 40)
        self.popup.resize(width, height)
        point = self.button.mapToGlobal(QPoint(0, self.button.height() + 4))
        x = min(max(screen.left() + 8, point.x()), screen.right() - width - 8)
        y = min(max(screen.top() + 8, point.y()), screen.bottom() - height - 8)
        self.popup.move(x, y)
        self.popup.show()
        if isinstance(self.body, FormBody):
            QTimer.singleShot(0, self.body.measure)
        if not was_visible:
            self.body.setFocus(Qt.FocusReason.PopupFocusReason)
