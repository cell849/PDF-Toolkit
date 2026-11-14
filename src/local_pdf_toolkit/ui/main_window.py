from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from local_pdf_toolkit.core.jobs import JobController
from local_pdf_toolkit.core.registry import ConverterRegistry


class MainWindow(QMainWindow):
    def __init__(self, registry: ConverterRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.setWindowTitle("Local PDF Toolkit")
        self.resize(840, 700)
        self.setAcceptDrops(True)
        self._paths = []
        self._pending = []
        self._closing = False
        self._stopping = False
        self._active = False
        self._row = 0
        self._editors = {}
        self._failed = set()
        self._results = {}
        self._retrying = False
        self._group = []
        self.jobs = JobController(self)
        self.jobs.progress.connect(self._progress)
        self.jobs.finished.connect(self._finished)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("Local PDF Toolkit")
        font = title.font()
        font.setPointSize(24)
        title.setFont(font)
        layout.addWidget(title)
        layout.addWidget(
            QLabel(
                "Drop documents/images here, or add files. Your documents stay on your computer."
            )
        )
        self.add_button = QPushButton("Add files…")
        self.add_button.clicked.connect(self._choose_files)
        self.clear_button = QPushButton("Clear files")
        self.clear_button.clicked.connect(self._clear)
        row = QHBoxLayout()
        row.addWidget(self.add_button)
        row.addWidget(self.clear_button)
        layout.addLayout(row)
        self.files = QListWidget()
        self.files.setAccessibleName("PDF files and conversion status")
        self.files.setMaximumHeight(220)
        self.files.itemDoubleClicked.connect(self._open_result)
        layout.addWidget(self.files)
        row = QHBoxLayout()
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        self.remove_button = QPushButton("Remove selected")
        self.retry_button = QPushButton("Retry failed/cancelled")
        self.cancel_selected = QPushButton("Cancel selected job")
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.remove_button.clicked.connect(self._remove)
        self.retry_button.clicked.connect(self._retry)
        self.cancel_selected.clicked.connect(self._cancel_one)
        for button in (
            self.up_button,
            self.down_button,
            self.remove_button,
            self.retry_button,
            self.cancel_selected,
        ):
            row.addWidget(button)
        layout.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a tool: merge, compress, image, Office…")
        self.search.textChanged.connect(self._filter_tools)
        layout.addWidget(self.search)
        self.operation_list = QListWidget()
        self.operation_list.setMaximumHeight(160)
        self.operation_list.setAccessibleName("Available conversion operations")
        self._operations = registry.list_operations()
        self.operation_list.addItems([spec.label for spec in self._operations])
        layout.addWidget(self.operation_list)
        if not self._operations:
            layout.addWidget(QLabel("No conversion tools available yet."))
        self.options_widget = QWidget()
        self.form = QFormLayout(self.options_widget)
        layout.addWidget(self.options_widget)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.destination = QLineEdit()
        self.destination.setPlaceholderText("Choose an existing output folder")
        self.destination.setAccessibleName("Output folder")
        self.browse = QPushButton("Output folder…")
        self.browse.clicked.connect(self._choose_directory)
        row = QHBoxLayout()
        row.addWidget(self.destination, 1)
        row.addWidget(self.browse)
        layout.addLayout(row)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.start_button = QPushButton("Convert")
        self.start_button.clicked.connect(self._start)
        self.start_button.setEnabled(bool(self._operations))
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_button = QPushButton("Open output folder")
        self.open_button.clicked.connect(self._open_directory)
        row.addWidget(self.start_button)
        row.addWidget(self.cancel_button)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self.operation_list.currentRowChanged.connect(self._options)
        self.operation_list.setCurrentRow(0 if self._operations else -1)
        self.statusBar().showMessage("Ready. Existing outputs will never be overwritten.")

    def _options(self, index):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors = {}
        if index < 0:
            return
        spec = self._operations[index]
        for option in spec.options:
            if option.choices:
                widget = QComboBox()
                for choice in option.choices:
                    widget.addItem(str(choice), choice)
                widget.setCurrentIndex(option.choices.index(option.default))
                getter = widget.currentData
            elif isinstance(option.default, bool):
                widget = QCheckBox()
                widget.setChecked(option.default)
                getter = widget.isChecked
            elif isinstance(option.default, int):
                widget = QSpinBox()
                widget.setRange(
                    option.minimum if option.minimum is not None else 0,
                    option.maximum if option.maximum is not None else 100,
                )
                widget.setValue(option.default)
                getter = widget.value
            else:
                widget = QLineEdit(str(option.default))
                if option.name == "password":
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
                getter = widget.text
            widget.setToolTip(option.description)
            self.form.addRow(option.label, widget)
            self._editors[option.name] = getter
        self.notice.setText(" ".join(spec.limitations))

    def add_paths(self, paths):
        if self._active:
            return
        for path in paths:
            path = Path(path).absolute()
            if path not in self._paths:
                self._paths.append(path)
                self.files.addItem(f"Ready — {path}")

    def dragEnterEvent(self, event):
        if not self._active and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths(url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile())
        event.acceptProposedAction()

    def _choose_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", "", "All files (*)")
        self.add_paths(paths)

    def _clear(self):
        self._paths.clear()
        self.files.clear()
        self._failed.clear()
        self._results.clear()

    def _choose_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Output folder")
        if path:
            self.destination.setText(path)

    def _open_directory(self):
        if Path(self.destination.text()).is_dir() and self.destination.text():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(self.destination.text()).absolute()))
            )

    def _set_active(self, active):
        self._active = active
        for widget in (
            self.add_button,
            self.clear_button,
            self.operation_list,
            self.options_widget,
            self.destination,
            self.browse,
            self.start_button,
            self.up_button,
            self.down_button,
            self.remove_button,
            self.retry_button,
            self.search,
        ):
            widget.setEnabled(not active)
        self.cancel_button.setEnabled(active)

    def _start(self):
        if (
            not self._paths
            or not self.destination.text()
            or not Path(self.destination.text()).is_dir()
        ):
            self.statusBar().showMessage("Add input files and choose an existing output folder.")
            return
        if self._retrying and hasattr(self, "_last_config"):
            self._converter, self._options_values, self._output_directory = self._last_config
        else:
            self._converter = self.registry.get(
                self._operations[self.operation_list.currentRow()].operation_id
            )
            self._options_values = {name: getter() for name, getter in self._editors.items()}
            self._output_directory = Path(self.destination.text()).absolute()
            self._last_config = (
                self._converter,
                dict(self._options_values),
                self._output_directory,
            )
        indices = sorted(self._failed) if self._retrying else list(range(len(self._paths)))
        self._retrying = False
        self._failed.clear()
        if self._converter.spec.input_mode == "multiple":
            self._pending = (
                [(indices[0], tuple(self._paths[i] for i in indices))] if indices else []
            )
            self._batch_indices = indices
        else:
            self._pending = [(i, self._paths[i]) for i in indices]
            self._batch_indices = []
        self._stopping = False
        self._set_active(True)
        for index in indices:
            self._results.pop(index, None)
            self.files.item(index).setText(f"Queued — {self._paths[index]}")
        self._next()

    def _next(self):
        if not self._pending or self._stopping:
            self._pending.clear()
            self._set_active(False)
            self.statusBar().showMessage(
                "Stopped." if self._stopping else "Finished. See file statuses."
            )
            if self._closing:
                self.close()
            return
        self._row, path = self._pending.pop(0)
        self._group = self._batch_indices or [self._row]
        for index in self._group:
            self.files.item(index).setText(f"Running — {self._paths[index]}")
        self.progress.setRange(0, 0)
        try:
            self.jobs.start(self._converter, path, self._output_directory, self._options_values)
        except Exception:
            self._finished((), ("conversion_failed", "Could not start conversion process."))

    def _progress(self, progress):
        self.progress.setRange(0, progress.total or 0)
        self.progress.setValue(progress.completed)
        self.statusBar().showMessage(
            f"Completed {progress.completed}/{progress.total} work units; saving safely…"
        )

    def _finished(self, paths, error):
        for index in self._group:
            message = f"Done — {len(paths)} outputs — {self._paths[index]}"
            if error:
                message = f"{error[0]} — {self._paths[index]} — {error[1]}"
                self._failed.add(index)
            else:
                self._results[index] = tuple(paths)
            self.files.item(index).setText(message)
            self.files.item(index).setToolTip(message + "\n" + "\n".join(map(str, paths)))
        QTimer.singleShot(0, self._next)

    def _cancel(self):
        self._stopping = True
        self.jobs.cancel()
        for index, path in self._pending:
            self._failed.add(index)
            self.files.item(index).setText(f"Cancelled — {path}")
        self.statusBar().showMessage(
            "Cancelling after the current page; cleaning temporary outputs…"
        )
        self.cancel_button.setEnabled(False)

    def _filter_tools(self, text):
        for index, spec in enumerate(self._operations):
            self.operation_list.item(index).setHidden(text.lower() not in spec.label.lower())

    def _move(self, delta):
        index = self.files.currentRow()
        target = index + delta
        if self._active or index < 0 or not 0 <= target < len(self._paths):
            return
        self._paths[index], self._paths[target] = self._paths[target], self._paths[index]
        item = self.files.takeItem(index)
        self.files.insertItem(target, item)
        self.files.setCurrentRow(target)
        self._failed.clear()
        self._results.clear()

    def _remove(self):
        index = self.files.currentRow()
        if self._active or index < 0:
            return
        self._paths.pop(index)
        self.files.takeItem(index)
        self._failed.clear()
        self._results.clear()

    def _retry(self):
        if self._active or not self._failed:
            return
        self._retrying = True
        self._start()

    def _cancel_one(self):
        if not self._active:
            return
        index = self.files.currentRow()
        if index < 0:
            return
        if index in self._group:
            self.jobs.cancel()
        elif any(i == index for i, _ in self._pending):
            self._pending = [(i, path) for i, path in self._pending if i != index]
            self._failed.add(index)
            if index >= 0:
                self.files.item(index).setText(f"Cancelled — {self._paths[index]}")

    def _open_result(self, item):
        for path in self._results.get(self.files.row(item), ()):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            break

    def closeEvent(self, event):
        if self._active:
            self._closing = True
            self._cancel()
            event.ignore()
        else:
            event.accept()
