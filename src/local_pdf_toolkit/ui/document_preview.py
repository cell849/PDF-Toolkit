"""Embedded, selected-document preview with a single cancellable renderer."""

import json
import tempfile
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from local_pdf_toolkit.converters.preview import PreviewConverter
from local_pdf_toolkit.core.jobs import JobController
from local_pdf_toolkit.ui.controls import ChoiceBox as QComboBox
from local_pdf_toolkit.ui.controls import NumericSpinBox as QSpinBox
from local_pdf_toolkit.ui.preview import PageCanvas

_MEDIA = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"}


class PreviewCanvas(PageCanvas):
    """Checkerboard beneath alpha pixels, with explicit zoom and pan state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fit_page = True

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.palette().color(QPalette.ColorRole.Base))
        bounds = self._image_rect.intersected(rect)
        if bounds.isEmpty():
            return
        painter.fillRect(bounds, QColor("#ffffff"))
        # Tiles scale with the view so the pattern stays legible at every zoom.
        tile = 12 / max(self.transform().m11(), 0.01)
        left, top = int(bounds.left() // tile), int(bounds.top() // tile)
        right, bottom = int(bounds.right() // tile), int(bounds.bottom() // tile)
        for y in range(top, bottom + 1):
            for x in range(left, right + 1):
                if (x + y) % 2:
                    painter.fillRect(QRectF(x * tile, y * tile, tile, tile), QColor("#d6dbe2"))

    def _fit_scale(self):
        if self._image_rect.isEmpty():
            return 1
        return max(
            0.01,
            min(
                (self.viewport().width() - 4) / self._image_rect.width(),
                (self.viewport().height() - 4) / self._image_rect.height(),
            ),
        )

    def view_state(self):
        if self._image_rect.isEmpty():
            return None
        center = self.mapToScene(self.viewport().rect().center())
        return (
            self.transform().m11() / self._fit_scale(),
            center.x() / self._image_rect.width(),
            center.y() / self._image_rect.height(),
            self.fit_page,
        )

    def show_pixmap(self, pixmap, state=None):
        self.scene().clear()
        self._image_rect = self.scene().addPixmap(pixmap).boundingRect()
        self.scene().setSceneRect(self._image_rect)
        self.resetTransform()
        self.fit_page = state[3] if state is not None else True
        if self.fit_page:
            self.fitInView(self._image_rect, Qt.AspectRatioMode.KeepAspectRatio)
        elif state is not None:
            zoom = state[0] * self._fit_scale()
            self.scale(zoom, zoom)
            self.centerOn(
                QPointF(state[1] * self._image_rect.width(), state[2] * self._image_rect.height())
            )
        self.viewport().update()

    def set_zoom(self, zoom=None):
        self.fit_page = zoom is None
        if self._image_rect.isEmpty():
            return
        if zoom is None:
            self.fitInView(self._image_rect, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            center = self.mapToScene(self.viewport().rect().center())
            self.resetTransform()
            self.scale(max(0.05, min(zoom, 8)), max(0.05, min(zoom, 8)))
            self.centerOn(center)

    def resizeEvent(self, event):
        QGraphicsView.resizeEvent(self, event)
        if self.fit_page and not self._image_rect.isEmpty():
            self.fitInView(self._image_rect, Qt.AspectRatioMode.KeepAspectRatio)


class DocumentPreview(QWidget):
    compare_requested = Signal()
    thumbnail_ready = Signal(object)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Selected document preview")
        self._source = None
        self._outputs = ()
        self._stale = False
        self._generation = 0
        self._active = None
        self._busy = False
        self._paused_active = None
        self._resume_needed = False
        self._displayed_key = None
        self._closing = False
        self._cleaned = False
        self._purge = False
        self._cache = OrderedDict()
        self._prepared = OrderedDict()
        self._prepared_details = {}
        self._shown_geometry = None
        self._transition = None
        self._temp = tempfile.TemporaryDirectory(prefix="pdf-toolkit-embedded-")
        self.jobs = JobController(self)
        self.jobs.finished.connect(self._finished)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._render)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.addTab("Original")
        self.tabs.addTab("Result")
        self.tabs.setTabEnabled(1, False)
        self.tabs.currentChanged.connect(self._switch)
        header.addWidget(self.tabs, 1)
        self.compare_button = QPushButton("Compare")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self.compare_requested)
        header.addWidget(self.compare_button)
        layout.addLayout(header)
        self.stale_label = QLabel("Previous run — settings changed")
        self.stale_label.setObjectName("previewStale")
        self.stale_label.setWordWrap(True)
        self.stale_label.hide()
        layout.addWidget(self.stale_label)
        self.output = QComboBox()
        self.output.setAccessibleName("Result file to preview")
        self.output.currentIndexChanged.connect(self._switch)
        self.output.hide()
        layout.addWidget(self.output)
        self.canvas = PreviewCanvas()
        layout.addWidget(self.canvas, 1)
        self.empty_message = QLabel("Document preview\nAdd a file to get started.")
        self.empty_message.setObjectName("muted")
        self.empty_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_message.setWordWrap(True)
        layout.addWidget(self.empty_message, 1)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Page"))
        self.page = QSpinBox()
        self.page.setAccessibleName("Preview page")
        self.page.setRange(1, 1)
        self.page.valueChanged.connect(self._schedule)
        bar.addWidget(self.page)
        self.page_count = QLabel("of —")
        bar.addWidget(self.page_count)
        bar.addStretch()
        self.zoom_out = QPushButton("−")
        self.zoom_out.setAccessibleName("Zoom out")
        self.zoom_out.clicked.connect(lambda: self._zoom_step(0.8))
        bar.addWidget(self.zoom_out)
        self.zoom = QComboBox()
        self.zoom.addItems(["Fit page", "100%"])
        self.zoom.setAccessibleName("Preview zoom")
        self.zoom.setEditable(True)
        self.zoom.lineEdit().setReadOnly(True)
        self.zoom.activated.connect(self._zoom_selected)
        bar.addWidget(self.zoom)
        self.zoom_in = QPushButton("+")
        self.zoom_in.setAccessibleName("Zoom in")
        self.zoom_in.clicked.connect(lambda: self._zoom_step(1.25))
        bar.addWidget(self.zoom_in)
        self.preview_controls = QWidget()
        self.preview_controls.setObjectName("inlineControl")
        self.preview_controls.setLayout(bar)
        bar.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.preview_controls)
        self.details = QLabel("")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.feedback = QLabel("Select a file to preview.")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self._sync_empty_state()

    def _sync_empty_state(self):
        loaded = self._source is not None
        self.empty_message.setVisible(not loaded)
        self.canvas.setVisible(loaded)
        self.tabs.setVisible(loaded)
        self.compare_button.setVisible(loaded and bool(self._outputs))
        self.preview_controls.setVisible(loaded)
        self.details.setVisible(loaded)
        self.feedback.setVisible(loaded)

    @property
    def running(self):
        return self.jobs.running

    def set_document(self, source, outputs=(), stale=False):
        if self._closing:
            return
        source = Path(source) if source is not None else None
        outputs = tuple(Path(path) for path in outputs)
        if source == self._source and outputs == self._outputs:
            self.set_stale(stale)
            return
        self._generation += 1
        self._debounce.stop()
        if self.jobs.running:
            self.jobs.cancel()
        self._source, self._outputs = source, outputs
        self._sync_empty_state()
        self._cache.clear()
        self._purge = True
        if not self.jobs.running:
            self._purge_files()
        self.output.blockSignals(True)
        self.output.clear()
        for path in outputs:
            self.output.addItem(path.name, path)
        self.output.blockSignals(False)
        self.tabs.blockSignals(True)
        self.tabs.setTabEnabled(1, bool(outputs))
        self.tabs.setCurrentIndex(1 if outputs else 0)
        self.tabs.blockSignals(False)
        self.compare_button.setEnabled(source is not None and bool(outputs))
        self.set_stale(stale)
        self.page.blockSignals(True)
        self.page.setRange(1, 1)
        self.page.setValue(1)
        self.page.blockSignals(False)
        self.page_count.setText("of —")
        self._transition = None
        self._shown_geometry = None
        self._clear_canvas()
        self.details.clear()
        self.output.setVisible(self.tabs.currentIndex() == 1 and len(outputs) > 1)
        self.feedback.setText("Preparing preview…" if source else "Select a file to preview.")
        if source:
            self._schedule()

    def set_stale(self, stale):
        self._stale = bool(stale)
        self.stale_label.setVisible(self._stale and bool(self._outputs))

    def set_busy(self, busy):
        """Pause decoding during other work; keep pixels until the renderer exits.

        Returns whether the renderer is idle. Callers that need exclusive
        decoding can wait for ``idle`` when this returns False.
        """
        if self._closing or self._busy == bool(busy):
            return not self.jobs.running
        self._busy = bool(busy)
        if self._busy:
            self._resume_needed |= self._debounce.isActive() or self.jobs.running
            self._debounce.stop()
            if self.jobs.running:
                self._paused_active = self._active
                self.jobs.cancel()
        elif self._resume_needed and not self.jobs.running:
            self._resume_latest()
        return not self.jobs.running

    def _resume_latest(self):
        self._resume_needed = False
        if self._path() is not None and self._key() != self._displayed_key:
            self._schedule()

    def clear(self):
        self.set_document(None)

    def _path(self):
        return self.output.currentData() if self.tabs.currentIndex() == 1 else self._source

    def _key(self):
        return (self._generation, self._path(), self.page.value())

    def _clear_canvas(self):
        self._displayed_key = None
        self.canvas.scene().clear()
        self.canvas._image_rect = QRectF()
        self.canvas.viewport().update()

    def _switch(self, *_):
        self._transition = (self._shown_geometry, self.canvas.view_state())
        self.output.setVisible(self.tabs.currentIndex() == 1 and len(self._outputs) > 1)
        # Keep a matching page number when possible; known counts clamp it below.
        self._schedule()

    def _schedule(self, *_):
        if self._closing or self._path() is None:
            return
        if self._busy:
            self._resume_needed = True
            return
        if self._transition is None and self._shown_geometry is not None:
            self._transition = (self._shown_geometry, self.canvas.view_state())
        self._debounce.start()
        if self.jobs.running and self._active != self._key():
            self.jobs.cancel()

    def _render(self):
        if self._closing or self._path() is None:
            return
        if self._busy:
            self._resume_needed = True
            return
        if self.jobs.running:
            return  # Completion schedules the newest selection only.
        key = self._key()
        if key in self._cache:
            self._cache.move_to_end(key)
            self._display(*self._cache[key])
            return
        path = self._path()
        if path.suffix.lower() in _MEDIA:
            self._clear_canvas()
            self.details.clear()
            self.feedback.setText(
                "Audio and video previews are unavailable. Use the output folder to open this file."
            )
            return
        # The first page establishes the page count for each selected side.
        known = next((info[1]["pages"] for k, info in self._cache.items() if k[1] == path), None)
        page = min(self.page.value(), known or 1)
        self.page.blockSignals(True)
        self.page.setValue(page)
        self.page.blockSignals(False)
        self._active = self._key()
        self.feedback.setText("Rendering preview…")
        try:
            self.jobs.start(
                PreviewConverter(),
                self._prepared.get(path, path),
                Path(self._temp.name),
                {"page": page},
            )
        except Exception:
            self._active = None
            self.feedback.setText("Could not start the preview worker.")

    def _finished(self, paths, error):
        active, self._active = self._active, None
        paused = self._paused_active is not None and active == self._paused_active
        self._paused_active = None
        if self._closing:
            self._cleanup()
            self.idle.emit()
            return
        if self._purge:
            self._purge_files()
        if paused:
            self._remove(paths)
            if not self._busy:
                self._resume_latest()
            self.idle.emit()
            return
        if active != self._key():
            self._remove(paths)
            if self._path() is not None:
                self._schedule()
            self.idle.emit()
            return
        if error:
            self._remove(paths)
            self._clear_canvas()
            self.details.clear()
            message = error[1]
            if "LibreOffice" in message:
                message = "Install LibreOffice locally to preview Office and text documents."
            self.feedback.setText("Preview unavailable. " + message)
        else:
            retained = None
            try:
                info = json.loads(Path(paths[1]).read_text(encoding="utf-8"))
                if self._path() in self._prepared_details:
                    info.update(self._prepared_details[self._path()])
                pixmap = QPixmap(str(paths[0]))
                if pixmap.isNull():
                    raise ValueError("Empty preview")
                if len(paths) > 2:
                    retained = Path(paths[2])
                    self._prepared[self._path()] = retained
                    self._prepared_details[self._path()] = {
                        name: info[name]
                        for name in ("source_bytes", "source_sha256", "office_approximation")
                    }
                    while len(self._prepared) > 2:
                        old_source, old = self._prepared.popitem(last=False)
                        self._prepared_details.pop(old_source, None)
                        self._remove((old,))
                self._cache[active] = (pixmap, info)
                while len(self._cache) > 4:
                    self._cache.popitem(last=False)
                self._display(pixmap, info)
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                self.feedback.setText("Could not read the rendered preview.")
            finally:
                self._remove(path for path in paths if Path(path) != retained)
        self.idle.emit()

    def _display(self, pixmap, info):
        geometry = (info.get("native_width"), info.get("native_height"), info.get("native_unit"))
        state = None
        if self._transition and self._transition[0] == geometry:
            state = self._transition[1]
        self._transition = None
        self._shown_geometry = geometry
        self.canvas.show_pixmap(pixmap, state)
        self.thumbnail_ready.emit(pixmap.copy())
        self._sync_zoom()
        self.page.blockSignals(True)
        self.page.setRange(1, info["pages"])
        self.page.setValue(info.get("page", self.page.value()))
        self.page.blockSignals(False)
        self._displayed_key = self._key()
        self._resume_needed = False
        self.page_count.setText(f"of {info['pages']:,}")
        dimensions = (
            f"{geometry[0]:g} × {geometry[1]:g} {geometry[2]}"
            if geometry[0] is not None and geometry[1] is not None
            else ""
        )
        size = info.get("source_bytes")
        self.details.setText(
            " · ".join(
                part for part in (f"{size:,} bytes" if size is not None else "", dimensions) if part
            )
        )
        self.feedback.setText(
            "Office preview uses the local fonts; layout may vary."
            if info.get("office_approximation")
            else "Preview of the selected file."
        )

    def _zoom_selected(self, index):
        self.canvas.set_zoom(None if index == 0 else 1)
        self._sync_zoom()

    def _zoom_step(self, factor):
        self.canvas.set_zoom(self.canvas.transform().m11() * factor)
        self._sync_zoom()

    def _sync_zoom(self):
        self.zoom.setCurrentText(
            "Fit page" if self.canvas.fit_page else f"{self.canvas.transform().m11() * 100:.0f}%"
        )

    @staticmethod
    def _remove(paths):
        for path in paths:
            with suppress(OSError):
                Path(path).unlink(missing_ok=True)

    def _purge_files(self):
        self._prepared.clear()
        self._prepared_details.clear()
        self._remove(Path(self._temp.name).iterdir())
        self._purge = False

    def shutdown(self):
        """Cancel promptly; return whether no worker can still access temporary files."""
        self._closing = True
        self._debounce.stop()
        if self.jobs.running:
            self.jobs.cancel()
            return False
        self._cleanup()
        return True

    def _cleanup(self):
        if not self._cleaned:
            self._cache.clear()
            self._prepared.clear()
            self._prepared_details.clear()
            self._temp.cleanup()
            self._cleaned = True

    def closeEvent(self, event):
        if self.shutdown():
            super().closeEvent(event)
        else:
            event.ignore()
