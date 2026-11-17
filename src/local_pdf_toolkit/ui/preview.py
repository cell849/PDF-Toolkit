"""A temporary, paged preview; its renderer never runs on the GUI thread."""

import json
import tempfile
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from local_pdf_toolkit.converters.preview import PreviewConverter
from local_pdf_toolkit.core.jobs import JobController
from local_pdf_toolkit.ui.controls import ChoiceBox as QComboBox
from local_pdf_toolkit.ui.controls import NumericSpinBox as QSpinBox


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


class ComparisonCanvas(PageCanvas):
    """Zoomable comparison only; PageCanvas retains redaction's fit behavior."""

    view_changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fit = True
        self._changing_view = False
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

    def load(self, path, regions=()):
        transform = self.transform()
        center = self.normalized_center()
        self._changing_view = True
        try:
            super().load(path, regions)
            if not self._fit:
                self.setTransform(transform)
                self.set_normalized_center(center)
        finally:
            self._changing_view = False

    def fit_page(self):
        self._fit = True
        if not self._image_rect.isEmpty():
            self._changing_view = True
            self.fitInView(self._image_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._changing_view = False

    def set_zoom(self, percent):
        self._fit = False
        center = self.normalized_center()
        self._changing_view = True
        self.resetTransform()
        self.scale(percent / 100, percent / 100)
        self.set_normalized_center(center)
        self._changing_view = False

    def normalized_center(self):
        bounds = self._image_rect
        if bounds.isEmpty():
            return QPointF(0.5, 0.5)
        center = self.mapToScene(self.viewport().rect().center())
        return QPointF(center.x() / bounds.width(), center.y() / bounds.height())

    def set_normalized_center(self, point):
        self.centerOn(point.x() * self._image_rect.width(), point.y() * self._image_rect.height())

    def resizeEvent(self, event):
        # Calling PageCanvas.resizeEvent would reset manual zoom on every resize.
        self._changing_view = True
        QGraphicsView.resizeEvent(self, event)
        if self._fit:
            self.fit_page()
        self._changing_view = False

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if hasattr(self, "_changing_view") and not self._changing_view:
            self.view_changed.emit(self)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            percent = min(
                800,
                max(
                    10, self.transform().m11() * 100 * (1.25 if event.angleDelta().y() > 0 else 0.8)
                ),
            )
            self.set_zoom(percent)
            self.view_changed.emit(self)
            event.accept()
            return
        super().wheelEvent(event)


class ComparisonDialog(QDialog):
    """Render two bounded pages sequentially, only after an explicit compare action."""

    def __init__(self, source, outputs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Before / after")
        self.resize(1040, 700)
        self._source = Path(source)
        self._temp = tempfile.TemporaryDirectory(prefix="pdf-toolkit-compare-")
        self._closing = False
        self._counts = {}
        self._pending = []
        self._syncing = False
        self.jobs = JobController(self)
        self.jobs.finished.connect(self._finished)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Output"))
        self.output = QComboBox()
        self.output.setAccessibleName("Converted file to compare")
        for path in outputs:
            path = Path(path)
            try:
                caption = f"{path.name} · {path.stat().st_size:,} bytes"
            except OSError:
                caption = f"{path.name} · unavailable"
            self.output.addItem(caption, path)
        bar.addWidget(self.output, 1)
        bar.addWidget(QLabel("Page"))
        self.page = QSpinBox()
        self.page.setAccessibleName("Comparison page")
        self.page.setRange(1, 1)
        bar.addWidget(self.page)
        layout.addLayout(bar)
        zoom_bar = QHBoxLayout()
        self.fit_button = QPushButton("Fit")
        self.fit_button.setAccessibleName("Fit both comparison pages")
        self.fit_button.clicked.connect(self._fit_pages)
        zoom_bar.addWidget(self.fit_button)
        self.actual_button = QPushButton("100% preview")
        self.actual_button.setToolTip("One rendered preview pixel per logical screen pixel.")
        self.actual_button.clicked.connect(lambda: self._set_zoom(100))
        zoom_bar.addWidget(self.actual_button)
        zoom_bar.addWidget(QLabel("Zoom"))
        self.zoom = QSpinBox()
        self.zoom.setAccessibleName("Comparison preview zoom percent")
        self.zoom.setRange(10, 800)
        self.zoom.setValue(100)
        self.zoom.setSuffix("%")
        self.zoom.setSingleStep(25)
        self.zoom.valueChanged.connect(self._set_zoom)
        zoom_bar.addWidget(self.zoom)
        self.sync = QCheckBox("Sync zoom and pan")
        self.sync.setChecked(True)
        zoom_bar.addWidget(self.sync)
        zoom_bar.addStretch()
        layout.addLayout(zoom_bar)
        panes = QHBoxLayout()
        self.canvases = []
        self.details = []
        for heading in ("Original", "Converted"):
            column = QVBoxLayout()
            title = QLabel(heading)
            title.setObjectName("section")
            column.addWidget(title)
            details = QLabel("Rendering preview…")
            details.setWordWrap(True)
            details.setAccessibleName(heading + " file size and dimensions")
            column.addWidget(details)
            canvas = ComparisonCanvas()
            canvas.view_changed.connect(self._sync_view)
            canvas.setAccessibleName(heading + " page preview")
            column.addWidget(canvas, 1)
            panes.addLayout(column, 1)
            self.canvases.append(canvas)
            self.details.append(details)
        layout.addLayout(panes, 1)
        self.feedback = QLabel(
            "100% uses rendered preview pixels; large sources are reduced to 1400 pixels per side. "
            "Drag or scroll to pan; Ctrl+wheel zooms. Shorter documents stay on their last page."
        )
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.output.currentIndexChanged.connect(self._output_changed)
        self.page.valueChanged.connect(self._request)
        self._request()

    def _fit_pages(self):
        self._syncing = True
        try:
            for canvas in self.canvases:
                canvas.fit_page()
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(self.canvases[0].transform().m11() * 100))
            self.zoom.blockSignals(False)
        finally:
            self._syncing = False

    def _set_zoom(self, percent):
        self._syncing = True
        try:
            for canvas in self.canvases:
                canvas.set_zoom(percent)
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(percent))
            self.zoom.blockSignals(False)
        finally:
            self._syncing = False

    def _sync_view(self, source):
        if self._syncing:
            return
        self._syncing = True
        try:
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(source.transform().m11() * 100))
            self.zoom.blockSignals(False)
            if self.sync.isChecked():
                for target in self.canvases:
                    if target is not source:
                        target.set_zoom(source.transform().m11() * 100)
                        target.set_normalized_center(source.normalized_center())
        finally:
            self._syncing = False

    def _output_changed(self, *_):
        self.page.blockSignals(True)
        self.page.setValue(1)
        self.page.blockSignals(False)
        self._request()

    def _request(self, *_):
        if self.jobs.running:
            return
        self.output.setEnabled(False)
        self.page.setEnabled(False)
        self._pending = list(enumerate((self._source, self.output.currentData())))
        self._syncing = True
        try:
            for canvas, detail in zip(self.canvases, self.details, strict=True):
                canvas.scene().clear()
                canvas._image_rect = QRectF()
                detail.setText("Rendering preview…")
        finally:
            self._syncing = False
        self._next()

    def _next(self):
        if not self._pending:
            self.output.setEnabled(True)
            self.page.setEnabled(True)
            count = max(
                self._counts.get(self._source, 1),
                self._counts.get(self.output.currentData(), 1),
            )
            self.page.blockSignals(True)
            self.page.setMaximum(count)
            self.page.blockSignals(False)
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(self.canvases[0].transform().m11() * 100))
            self.zoom.blockSignals(False)
            return
        self._side, self._path = self._pending.pop(0)
        self._rendered_page = min(self.page.value(), self._counts.get(self._path, 1))
        try:
            self.jobs.start(
                PreviewConverter(),
                self._path,
                Path(self._temp.name),
                {"page": self._rendered_page},
            )
        except Exception:
            self.details[self._side].setText("Could not start preview.")
            self._next()

    def _finished(self, paths, error):
        if self._closing:
            self._temp.cleanup()
            super().done(QDialog.DialogCode.Rejected)
            return
        if error:
            self.details[self._side].setText("Preview unavailable. " + error[1])
        else:
            try:
                info = json.loads(paths[1].read_text(encoding="utf-8"))
                self._counts[self._path] = info["pages"]
                self.canvases[self._side].load(paths[0])
                width, height = info.get("native_width"), info.get("native_height")
                dimensions = (
                    f"{width:g} × {height:g} {info['native_unit']}"
                    if width is not None and height is not None
                    else "Dimensions unavailable"
                )
                size = info.get("source_bytes")
                details = f"{size:,} bytes · " if size is not None else ""
                self.details[self._side].setText(
                    f"{self._path.name}\n{details}{dimensions}\n"
                    f"Page {self._rendered_page} of {info['pages']}"
                    + (
                        " · Office layout is approximate"
                        if info.get("office_approximation")
                        else ""
                    )
                )
            except (OSError, ValueError, KeyError, TypeError):
                self.details[self._side].setText("Could not read preview details.")
            finally:
                for path in paths:
                    with suppress(OSError):
                        path.unlink(missing_ok=True)
        self._next()

    def done(self, result):
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
