"""Accessible page grid with a single lazy thumbnail worker and bounded pixel cache."""

import json
import tempfile
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from local_pdf_toolkit.converters.page_organizer import (
    OrganizerPreviewConverter,
    canonical_plan,
)
from local_pdf_toolkit.core.jobs import JobController

CACHE_ITEMS = 32


class PageGrid(QListWidget):
    move_requested = Signal(int)
    drop_requested = Signal(int)
    delete_requested = Signal()
    rotate_requested = Signal()
    undo_requested = Signal()
    viewport_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Snap)
        self.setWrapping(True)
        self.setIconSize(QSize(128, 164))
        self.setGridSize(QSize(162, 216))
        self.setSpacing(4)
        self.setWordWrap(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setMinimumHeight(280)
        self.setAccessibleName("PDF pages in output order")
        self.setAccessibleDescription(
            "Select pages with Control or Shift. Drag to reorder. Alt Left and Alt Right move "
            "selected pages; Delete removes pages; Control R rotates; Control Z undoes."
        )
        self.verticalScrollBar().valueChanged.connect(self.viewport_changed)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            metrics = self.fontMetrics()
            self.setGridSize(
                QSize(
                    max(162, metrics.horizontalAdvance("Source page 10000 +270°") + 16),
                    164 + metrics.lineSpacing() * 3 + 24,
                )
            )

    def dropEvent(self, event):
        if event.source() is not self:
            event.ignore()
            return
        target = self.indexAt(event.position().toPoint())
        row = target.row() if target.isValid() else self.count()
        if target.isValid():
            bounds = self.visualRect(target)
            if event.position().x() > bounds.center().x():
                row += 1
        self.drop_requested.emit(row)
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()

    def keyPressEvent(self, event):
        key, modifiers = event.key(), event.modifiers()
        if modifiers == Qt.KeyboardModifier.AltModifier and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
        ):
            self.move_requested.emit(-1 if key == Qt.Key.Key_Left else 1)
        elif key == Qt.Key.Key_Delete and modifiers == Qt.KeyboardModifier.NoModifier:
            self.delete_requested.emit()
        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_R:
            self.rotate_requested.emit()
        elif modifiers == Qt.KeyboardModifier.ControlModifier and key == Qt.Key.Key_Z:
            self.undo_requested.emit()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_changed.emit()


class PageOrganizerControl(QWidget):
    changed = Signal()
    sources_requested = Signal(object)
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("Visual PDF page organizer")
        self._paths = ()
        self._sources = []
        self._prepared = {}
        self._pages = []
        self._history = []
        self._cache = OrderedDict()
        self._placeholder_icon = self._thumbnail_icon()
        self._failed = set()
        self._generation = 0
        self._active = None
        self._pending_scan = False
        self._closing = False
        self._cleaned = False
        self._busy = False
        self._insert_position = None
        self.error_message = "Add a PDF to arrange its pages."
        self._temp = tempfile.TemporaryDirectory(prefix="pdf-toolkit-organizer-")
        self.jobs = JobController(self)
        self.jobs.finished.connect(self._finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._work)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.help = QLabel(
            "Drag pages into order. Use Control or Shift to select several pages. "
            "Insert PDFs after the selection; save the arrangement as a new copy."
        )
        self.help.setWordWrap(True)
        self.help.setObjectName("muted")
        layout.addWidget(self.help)
        bar = QHBoxLayout()
        self.insert_button = QPushButton("Insert PDF…")
        self.insert_button.clicked.connect(self._choose_insert)
        bar.addWidget(self.insert_button)
        edit_bar = QHBoxLayout()
        self.before_button = QPushButton("Move earlier")
        self.before_button.setToolTip("Move selected pages earlier (Alt+Left)")
        self.before_button.clicked.connect(lambda: self.move_selected(-1))
        edit_bar.addWidget(self.before_button)
        self.after_button = QPushButton("Move later")
        self.after_button.setToolTip("Move selected pages later (Alt+Right)")
        self.after_button.clicked.connect(lambda: self.move_selected(1))
        edit_bar.addWidget(self.after_button)
        self.rotate_button = QPushButton("Rotate 90°")
        self.rotate_button.setToolTip("Rotate selected pages clockwise (Ctrl+R)")
        self.rotate_button.clicked.connect(self.rotate_selected)
        edit_bar.addWidget(self.rotate_button)
        self.delete_button = QPushButton("Remove pages")
        self.delete_button.setToolTip("Remove selected pages from the new copy (Delete)")
        self.delete_button.clicked.connect(self.delete_selected)
        edit_bar.addWidget(self.delete_button)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setToolTip("Undo the last arrangement change (Ctrl+Z)")
        self.undo_button.clicked.connect(self.undo)
        bar.addWidget(self.undo_button)
        self.reload_button = QPushButton("Reload pages")
        self.reload_button.clicked.connect(self.reload)
        bar.addWidget(self.reload_button)
        bar.addStretch()
        layout.addLayout(bar)
        layout.addLayout(edit_bar)
        self.grid = PageGrid()
        self.grid.itemSelectionChanged.connect(self._selection_changed)
        self.grid.move_requested.connect(self.move_selected)
        self.grid.drop_requested.connect(self.move_selected_to)
        self.grid.delete_requested.connect(self.delete_selected)
        self.grid.rotate_requested.connect(self.rotate_selected)
        self.grid.undo_requested.connect(self.undo)
        self.grid.viewport_changed.connect(self._schedule)
        layout.addWidget(self.grid, 1)
        self.feedback = QLabel(self.error_message)
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        self._selection_changed()

    @property
    def running(self):
        return self.jobs.running

    def sources(self):
        return self._paths

    def set_sources(self, paths):
        if self._closing:
            return
        paths = tuple(dict.fromkeys(Path(path).resolve() for path in paths))
        if paths == self._paths:
            return
        self._generation += 1
        self._paths = paths
        self._pending_scan = bool(paths)
        self.error_message = (
            "Preparing page thumbnails…" if paths else "Add a PDF to arrange its pages."
        )
        self.feedback.setText(self.error_message)
        self._timer.stop()
        if self.jobs.running:
            self.jobs.cancel()
        if not paths:
            self._pages, self._sources = [], []
            self._history.clear()
            self.grid.clear()
            if not self.jobs.running:
                self._remove(self._prepared.values())
                self._prepared.clear()
                self._cache.clear()
        self.changed.emit()
        self._selection_changed()
        self._schedule()

    def reload(self):
        """Explicitly discard stale byte bindings and read the selected files again."""
        paths, self._paths = self._paths, ()
        self.set_sources(paths)

    def value(self):
        if self.error_message or self._pending_scan or not self._pages:
            return ""
        return canonical_plan({"version": 1, "sources": self._sources, "pages": self._pages})

    def _choose_insert(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Insert PDF pages", "", "PDF files (*.pdf)")
        if paths:
            self.insert_files(paths)

    def insert_files(self, paths):
        selected = self.selected_rows()
        self._insert_position = max(selected) + 1 if selected else len(self._pages)
        new_paths = tuple(dict.fromkeys((*self._paths, *(Path(path).resolve() for path in paths))))
        self.set_sources(new_paths)
        self.sources_requested.emit(new_paths)

    def selected_rows(self):
        return sorted(self.grid.row(item) for item in self.grid.selectedItems())

    def _selection_changed(self):
        rows = self.selected_rows()
        enabled = bool(rows) and not self._pending_scan and not self._busy
        self.before_button.setEnabled(enabled and rows[0] > 0)
        self.after_button.setEnabled(enabled and rows[-1] < len(self._pages) - 1)
        self.rotate_button.setEnabled(enabled)
        self.delete_button.setEnabled(enabled and len(rows) < len(self._pages))
        self.undo_button.setEnabled(
            bool(self._history) and not self._pending_scan and not self._busy
        )
        self.insert_button.setEnabled(not self._pending_scan and not self._busy)
        self.reload_button.setEnabled(bool(self._paths) and not self._busy)
        if not self.error_message:
            self.feedback.setText(f"{len(self._pages):,} pages · {len(rows):,} selected")

    def _remember(self):
        self._history.append([dict(page) for page in self._pages])
        del self._history[:-20]

    def move_selected(self, delta):
        rows = self.selected_rows()
        if not rows or self._pending_scan or self._busy:
            return
        if delta < 0 and rows[0] > 0:
            self.move_selected_to(rows[0] - 1)
        elif delta > 0 and rows[-1] < len(self._pages) - 1:
            self.move_selected_to(rows[-1] + 2)

    def move_selected_to(self, destination):
        rows = self.selected_rows()
        if not rows or self._pending_scan or self._busy:
            return
        selected = set(rows)
        destination = max(0, min(destination, len(self._pages)))
        insertion = destination - sum(row < destination for row in rows)
        moved = [self._pages[row] for row in rows]
        rest = [page for row, page in enumerate(self._pages) if row not in selected]
        result = rest[:insertion] + moved + rest[insertion:]
        if result == self._pages:
            return
        self._remember()
        self._pages = result
        self._rebuild(range(insertion, insertion + len(moved)))

    def rotate_selected(self):
        rows = self.selected_rows()
        if not rows or self._pending_scan or self._busy:
            return
        self._remember()
        for row in rows:
            self._pages[row] = {
                **self._pages[row],
                "rotation": (self._pages[row]["rotation"] + 90) % 360,
            }
        self._rebuild(rows)

    def delete_selected(self):
        rows = set(self.selected_rows())
        if not rows or len(rows) == len(self._pages) or self._pending_scan or self._busy:
            return
        self._remember()
        self._pages = [page for row, page in enumerate(self._pages) if row not in rows]
        self._rebuild([min(min(rows), len(self._pages) - 1)])

    def undo(self):
        if self._history and not self._pending_scan and not self._busy:
            self._pages = self._history.pop()
            self._rebuild()

    @staticmethod
    def _thumbnail_icon(pixmap=None):
        canvas = QPixmap(128, 164)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        if pixmap is None:
            painter.setPen(QPen(QColor(130, 140, 150, 100), 1))
            painter.drawRoundedRect(8, 4, 112, 154, 4, 4)
            painter.drawText(canvas.rect(), Qt.AlignmentFlag.AlignCenter, "…")
        else:
            fitted = pixmap.scaled(
                120,
                156,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap((128 - fitted.width()) // 2, (164 - fitted.height()) // 2, fitted)
        painter.end()
        return QIcon(canvas)

    @staticmethod
    def _key(page):
        return page["path"], page["page"], page["rotation"]

    def _rebuild(self, selected=()):
        selected = set(selected)
        self.grid.blockSignals(True)
        self.grid.clear()
        for row, page in enumerate(self._pages):
            name = Path(page["path"]).name
            label = f"{row + 1} · {name}\nSource page {page['page']}"
            if page["rotation"]:
                label += f" · +{page['rotation']}°"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dict(page))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, label.replace("\n", ", "))
            item.setToolTip(label)
            key = self._key(page)
            item.setIcon(self._cache.get(key) or self._placeholder_icon)
            self.grid.addItem(item)
            item.setSelected(row in selected)
        self.grid.blockSignals(False)
        self._selection_changed()
        self.changed.emit()
        self._schedule()

    def _schedule(self, *_):
        if not self._closing and not self._busy:
            self._timer.start()

    def _work(self):
        if self._closing or self._busy or self.jobs.running:
            return
        if self._pending_scan:
            self._active = (self._generation, "scan", None)
            args = self._paths, {"mode": "scan"}
        else:
            if self.error_message:
                return
            # Render visible cells only; no raster buffer scales with document length.
            bounds = self.grid.viewport().rect()
            candidates = []
            visible = 0
            for row in range(self.grid.count()):
                if self.grid.visualItemRect(self.grid.item(row)).intersects(bounds):
                    visible += 1
                    if visible > CACHE_ITEMS:
                        break
                    key = self._key(self._pages[row])
                    if key not in self._cache and key not in self._failed:
                        candidates.append(key)
                        break
            if not candidates:
                return
            key = candidates[0]
            self._active = (self._generation, "thumbnail", key)
            args = self._prepared[key[0]], {"page": key[1], "rotation": key[2]}
        try:
            self.jobs.start(OrganizerPreviewConverter(), args[0], Path(self._temp.name), args[1])
        except Exception:
            self._active = None
            self.error_message = "Could not start the page preview worker."
            self.feedback.setText(self.error_message)
            self.changed.emit()

    def _finished(self, paths, error):
        active, self._active = self._active, None
        if self._closing:
            self._cleanup()
            self.idle.emit()
            return
        if active is None or active[0] != self._generation:
            self._remove(paths)
            if not self._paths:
                self._remove(self._prepared.values())
                self._prepared.clear()
                self._cache.clear()
            self._schedule()
            self.idle.emit()
            return
        if error and error[0] == "cancelled":
            self._remove(paths)
            self._schedule()
            self.idle.emit()
            return
        if active[1] == "scan":
            self._pending_scan = False
            if error:
                self.error_message = error[1]
                self.feedback.setText(self.error_message)
            else:
                try:
                    manifest = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
                    old = {item["path"]: item["sha256"] for item in self._sources}
                    sources = manifest["sources"]
                    preserved = {
                        item["path"] for item in sources if old.get(item["path"]) == item["sha256"]
                    }
                    pages = [page for page in self._pages if page["path"] in preserved]
                    added = [
                        {"path": source["path"], "page": index, "rotation": 0}
                        for source in sources
                        if source["path"] not in preserved
                        for index in range(1, source["pages"] + 1)
                    ]
                    position = min(
                        self._insert_position if self._insert_position is not None else len(pages),
                        len(pages),
                    )
                    self._pages = pages[:position] + added + pages[position:]
                    self._sources = sources
                    old_prepared = tuple(self._prepared.values())
                    self._prepared = {
                        key: Path(self._temp.name) / value
                        for key, value in manifest["prepared"].items()
                    }
                    self._remove((*old_prepared, paths[0]))
                    self._cache.clear()
                    self._failed.clear()
                    self._history.clear()
                    self.error_message = ""
                    self._insert_position = None
                    self._rebuild()
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    self._remove(paths)
                    self.error_message = "Could not read PDF page information. Reload the sources."
                    self.feedback.setText(self.error_message)
            self.changed.emit()
            self._selection_changed()
        else:
            key = active[2]
            if error:
                self._failed.add(key)
                self.feedback.setText("A page thumbnail is unavailable. " + error[1])
            else:
                pixmap = QPixmap(str(paths[0])) if paths else QPixmap()
                if pixmap.isNull():
                    self._failed.add(key)
                else:
                    self._cache[key] = self._thumbnail_icon(pixmap)
                    while len(self._cache) > CACHE_ITEMS:
                        expired, _ = self._cache.popitem(last=False)
                        for row, page in enumerate(self._pages):
                            if self._key(page) == expired:
                                self.grid.item(row).setIcon(self._placeholder_icon)
                    for row, page in enumerate(self._pages):
                        if self._key(page) == key:
                            self.grid.item(row).setIcon(self._cache[key])
            self._remove(paths)
        self._schedule()
        self.idle.emit()

    @staticmethod
    def _remove(paths):
        for path in paths:
            with suppress(OSError):
                Path(path).unlink(missing_ok=True)

    def set_busy(self, busy):
        self._busy = bool(busy)
        self.grid.setEnabled(not self._busy)
        self._selection_changed()
        if self._busy:
            self._timer.stop()
            if self.jobs.running:
                self.jobs.cancel()
        else:
            self._schedule()
        return not self.jobs.running

    def shutdown(self):
        self._closing = True
        self._timer.stop()
        if self.jobs.running:
            self.jobs.cancel()
            return False
        self._cleanup()
        return True

    def _cleanup(self):
        if not self._cleaned:
            self._cache.clear()
            self._temp.cleanup()
            self._cleaned = True

    def closeEvent(self, event):
        if self.shutdown():
            super().closeEvent(event)
        else:
            event.ignore()
