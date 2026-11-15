"""A temporary, paged preview; its renderer never runs on the GUI thread."""

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from local_pdf_toolkit.converters.preview import PreviewConverter
from local_pdf_toolkit.core.jobs import JobController


class PageCanvas(QGraphicsView):
    """Image coordinates are independent of zoom; rectangles use normalized bounds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAccessibleName("Document page preview")
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._image_rect = QRectF()
        self._marking = False
        self._start = None
        self._rubber = None
        self.regions = []

    def load(self, path, regions=()):
        self.scene().clear()
        self._rubber = None
        self._start = None
        self.regions = list(regions)
        pixmap = QPixmap(str(path))
        self._image_rect = self.scene().addPixmap(pixmap).boundingRect()
        self.scene().setSceneRect(self._image_rect)
        for region in regions:
            self._draw(region)
        self.fitInView(self._image_rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _draw(self, region):
        x0, y0, x1, y1 = region
        bounds = self._image_rect
        return self.scene().addRect(
            QRectF(
                x0 * bounds.width(),
                y0 * bounds.height(),
                (x1 - x0) * bounds.width(),
                (y1 - y0) * bounds.height(),
            ),
            QPen(QColor("#0066cc"), 2),
            QColor(0, 0, 0, 180),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._image_rect.isEmpty():
            self.fitInView(self._image_rect, Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if self._marking and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self._image_rect.contains(point):
                self._start = point
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is not None:
            if self._rubber is not None:
                self.scene().removeItem(self._rubber)
            rect = (
                QRectF(self._start, self.mapToScene(event.position().toPoint()))
                .normalized()
                .intersected(self._image_rect)
            )
            self._rubber = self.scene().addRect(
                rect, QPen(QColor("#0066cc"), 2), QColor(0, 0, 0, 180)
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._start is not None:
            rect = (
                QRectF(self._start, self.mapToScene(event.position().toPoint()))
                .normalized()
                .intersected(self._image_rect)
            )
            self._start = None
            if self._rubber is not None:
                self.scene().removeItem(self._rubber)
                self._rubber = None
            if rect.width() >= 2 and rect.height() >= 2:
                bounds = self._image_rect
                region = (
                    rect.left() / bounds.width(),
                    rect.top() / bounds.height(),
                    rect.right() / bounds.width(),
                    rect.bottom() / bounds.height(),
                )
                self.regions.append(region)
                self._draw(region)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PreviewDialog(QDialog):
    def __init__(self, path, parent=None, marking=False, regions=None, source_digest=""):
        super().__init__(parent)
        self.setWindowTitle("Mark redactions" if marking else "Document preview")
        self.resize(880, 740)
        self._source = Path(path)
        self._temp = tempfile.TemporaryDirectory(prefix="pdf-toolkit-preview-")
        self._closing = False
        self._marking = marking
        self._office_preview = False
        self.marked = dict(regions or {})
        self._current = 1
        self.source_digest = source_digest
        self.jobs = JobController(self)
        self.jobs.finished.connect(self._finished)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Page"))
        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.valueChanged.connect(self._request)
        bar.addWidget(self.page)
        bar.addStretch()
        self.clear = QPushButton("Clear marks on page")
        self.clear.clicked.connect(self._clear)
        self.clear.setVisible(marking)
        bar.addWidget(self.clear)
        layout.addLayout(bar)
        self.canvas = PageCanvas()
        self.canvas._marking = marking
        layout.addWidget(self.canvas, 1)
        self.feedback = QLabel("Rendering preview…")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self.done_button = QPushButton("Use marked areas" if marking else "Close")
        self.done_button.clicked.connect(self.accept if marking else self.close)
        layout.addWidget(self.done_button)
        self.done_button.setEnabled(False)
        self._request(1)

    def _save_marks(self):
        if self._marking and not self.canvas._image_rect.isEmpty():
            self.marked[self._current] = list(self.canvas.regions)

    def _request(self, page):
        if self.jobs.running:
            return
        self._save_marks()
        self._current = page
        self.canvas.scene().clear()
        self.canvas._rubber = None
        self.canvas._start = None
        self.canvas._image_rect = QRectF()
        self.canvas.regions = []
        self.canvas.setEnabled(False)
        self.page.setEnabled(False)
        self.clear.setEnabled(False)
        self.done_button.setEnabled(False)
        self.feedback.setText("Rendering preview…")
        try:
            self.jobs.start(PreviewConverter(), self._source, Path(self._temp.name), {"page": page})
        except Exception:
            self.feedback.setText("Could not start preview.")
            self.done_button.setEnabled(not self._marking)

    def _finished(self, paths, error):
        if self._closing:
            self._temp.cleanup()
            self.reject()
            return
        self.page.setEnabled(True)
        self.clear.setEnabled(True)
        self.done_button.setEnabled(True)
        if error:
            self.feedback.setText(error[1])
            self.done_button.setEnabled(not self._marking)
            return
        info = json.loads(paths[1].read_text())
        if self._marking and self.source_digest and info["source_sha256"] != self.source_digest:
            paths[0].unlink(missing_ok=True)
            paths[1].unlink(missing_ok=True)
            self.feedback.setText("The source changed. Close this window and mark it again.")
            self.done_button.setEnabled(False)
            return
        self.source_digest = info["source_sha256"]
        self._office_preview |= info.get("office_approximation", False)
        self.page.blockSignals(True)
        self.page.setRange(1, info["pages"])
        self.page.blockSignals(False)
        if len(paths) > 2:
            self._source = paths[2]
        self.canvas.setEnabled(True)
        self.canvas.load(paths[0], self.marked.get(self._current, ()))
        # QPixmap owns the loaded pixels; retain only the current page in memory.
        paths[0].unlink(missing_ok=True)
        paths[1].unlink(missing_ok=True)
        self.feedback.setText(
            (
                "Drag over each area to remove. Review every page before applying."
                if self._marking
                else "Preview only. Source files are unchanged."
            )
            + (
                " Office layout is approximate and depends on local fonts."
                if self._office_preview
                else ""
            )
        )

    def _clear(self):
        self.canvas.regions = []
        self.marked[self._current] = []
        for item in list(self.canvas.scene().items()):
            from PySide6.QtWidgets import QGraphicsRectItem

            if isinstance(item, QGraphicsRectItem):
                self.canvas.scene().removeItem(item)

    def done(self, result):
        self._save_marks()
        if self.jobs.running:
            self._closing = True
            self.jobs.cancel()
            return
        self._temp.cleanup()
        super().done(result)

    def closeEvent(self, event):
        if self.jobs.running:
            self._closing = True
            self.jobs.cancel()
            event.ignore()
        else:
            self._temp.cleanup()
            super().closeEvent(event)
