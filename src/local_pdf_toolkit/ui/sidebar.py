"""Original category symbols and a compact, accessible navigation rail."""

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QListWidget, QPushButton, QStyledItemDelegate, QStyleOptionViewItem


class SidebarToggle(QPushButton):
    def _keyboard_focus(self, value):
        self.setProperty("keyboardFocus", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self._keyboard_focus(False)
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self._keyboard_focus(
            event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        )
        super().focusInEvent(event)


def category_icon(index, color):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(
        QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )
    if index == 0:
        for x in (4, 14):
            for y in (4, 14):
                painter.drawRoundedRect(QRectF(x, y, 6, 6), 1, 1)
    elif index == 1:
        painter.drawLine(4, 7, 20, 7)
        painter.drawLine(16, 3, 20, 7)
        painter.drawLine(16, 11, 20, 7)
        painter.drawLine(20, 17, 4, 17)
        painter.drawLine(8, 13, 4, 17)
        painter.drawLine(8, 21, 4, 17)
    elif index == 2:
        painter.drawRoundedRect(QRectF(3, 4, 18, 16), 2, 2)
        painter.drawEllipse(QRectF(6, 7, 3, 3))
        path = QPainterPath()
        path.moveTo(5, 18)
        path.lineTo(11, 12)
        path.lineTo(14, 15)
        path.lineTo(17, 11)
        path.lineTo(20, 16)
        painter.drawPath(path)
    elif index == 3:
        painter.drawRoundedRect(QRectF(3, 3, 12, 15), 1, 1)
        painter.drawRoundedRect(QRectF(8, 7, 12, 15), 1, 1)
    elif index == 4:
        for a, b in ((3, 9), (21, 15)):
            painter.drawLine(a, 4, b, 10)
            painter.drawLine(a, 20, b, 14)
        painter.drawLine(9, 5, 9, 10)
        painter.drawLine(4, 10, 9, 10)
        painter.drawLine(15, 14, 15, 19)
        painter.drawLine(15, 14, 20, 14)
    elif index == 5:
        painter.drawRoundedRect(QRectF(5, 2, 14, 20), 2, 2)
        for y in (8, 12, 16):
            painter.drawLine(8, y, 16, y)
    elif index == 6:
        path = QPainterPath()
        path.moveTo(2, 12)
        path.cubicTo(8, 3, 16, 3, 22, 12)
        path.cubicTo(16, 21, 8, 21, 2, 12)
        painter.drawPath(path)
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        painter.drawLine(3, 21, 21, 3)
    else:
        painter.drawRoundedRect(QRectF(5, 10, 14, 11), 2, 2)
        painter.drawArc(QRectF(8, 3, 8, 14), 0, 180 * 16)
        painter.drawLine(12, 14, 12, 17)
    painter.end()
    return QIcon(pixmap)


class _NavigationDelegate(QStyledItemDelegate):
    def initStyleOption(self, option: QStyleOptionViewItem, index):
        super().initStyleOption(option, index)
        if self.parent().collapsed:
            option.text = ""
            option.decorationPosition = QStyleOptionViewItem.Position.Top
            option.decorationAlignment = Qt.AlignmentFlag.AlignCenter


class CategoryNavigation(QListWidget):
    activate_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.collapsed = False
        self.previous_row = -1
        self.setIconSize(QSize(24, 24))
        self.setItemDelegate(_NavigationDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def mousePressEvent(self, event):
        self.previous_row = self.currentRow()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self.currentItem() is not None:
                self.activate_requested.emit(self.currentItem().text())
            event.accept()
            return
        super().keyPressEvent(event)

    def refresh_icons(self):
        for index in range(self.count()):
            item = self.item(index)
            item.setIcon(category_icon(index, self.palette().color(QPalette.ColorRole.Text)))
            item.setToolTip(item.text())
            item.setData(Qt.ItemDataRole.AccessibleTextRole, item.text())
            item.setSizeHint(QSize(40, max(42, self.fontMetrics().height() + 16)))

    def set_collapsed(self, value):
        self.collapsed = value
        self.setProperty("compact", value)
        self.style().unpolish(self)
        self.style().polish(self)
        self.refresh_icons()
        self.viewport().update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.PaletteChange, QEvent.Type.FontChange):
            self.refresh_icons()
