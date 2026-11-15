from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QSpinBox,
)

from local_pdf_toolkit.core.jobs import JobController
from local_pdf_toolkit.core.registry import ConverterRegistry


class MainWindow(QMainWindow):
    def __init__(self, registry: ConverterRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.setWindowTitle("Local PDF Toolkit")
        self.resize(1160, 850)
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
        from local_pdf_toolkit.ui.shell import build_window

        build_window(self)

    def _show_library(self):
        if not self._active:
            self.pages.setCurrentWidget(self.dashboard)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "form"):
            from PySide6.QtWidgets import QFormLayout

            policy = (
                QFormLayout.RowWrapPolicy.WrapAllRows
                if self.width() < 980
                else QFormLayout.RowWrapPolicy.WrapLongRows
            )
            self.form.setRowWrapPolicy(policy)

    def _appearance_changed(self, *_):
        from local_pdf_toolkit.ui.design import apply_theme

        apply_theme(self)

    def _select_tool(self, index):
        if self._active:
            return
        self.operation_list.setCurrentRow(index)
        self.pages.setCurrentWidget(self.workspace)

    def _category_changed(self, index):
        from local_pdf_toolkit.ui.shell import CATEGORIES

        self._category = CATEGORIES[index] if index >= 0 else "All tools"
        self.pages.setCurrentWidget(self.dashboard)
        self._filter_tools(self.search.text())

    def _options(self, index):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors = {}
        self.start_button.setEnabled(index >= 0 and not self._active)
        if index < 0:
            self.notice.clear()
            return
        spec = self._operations[index]
        self.tool_title.setText(spec.label.replace(" / resize / compress", ""))
        self.tool_hint.setText(
            "Files are combined in the order below."
            if spec.input_mode == "multiple"
            else "Each file is processed separately. Originals stay untouched."
        )
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
                self.files.addItem(f"Ready — {path.name}")
                self.files.item(self.files.count() - 1).setToolTip(str(path))
        self._sync_files()
        if self._paths:
            self.pages.setCurrentWidget(self.workspace)

    def dragEnterEvent(self, event):
        if not self._active and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_paths(url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile())
        event.acceptProposedAction()

    def _choose_files(self):
        if self._active:
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", "", "All files (*)")
        self.add_paths(paths)

    def _sync_files(self):
        self.files.setVisible(bool(self._paths))
        self.drop_hint.setVisible(not self._paths)
        for button in (
            self.up_button,
            self.down_button,
            self.remove_button,
            self.retry_button,
            self.cancel_selected,
        ):
            button.setVisible(bool(self._paths))
        self.file_heading.setText(f"Files · {len(self._paths)}" if self._paths else "Files")

    def _clear(self):
        self._paths.clear()
        self.files.clear()
        self._failed.clear()
        self._results.clear()
        self._sync_files()

    def _choose_directory(self):
        if self._active:
            return
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
            self.navigation,
            self.back_button,
        ):
            widget.setEnabled(not active)
        self.cancel_button.setEnabled(active)
        self.start_button.setEnabled(not active and self.operation_list.currentRow() >= 0)

    def _start(self):
        if self._active or (not self._retrying and self.operation_list.currentRow() < 0):
            return
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
            self.files.item(index).setText(f"Queued — {self._paths[index].name}")
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
            self.files.item(index).setText(f"Running — {self._paths[index].name}")
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
            message = f"Done — {len(paths)} outputs — {self._paths[index].name}"
            if error:
                message = f"{error[0]} — {self._paths[index].name} — {error[1]}"
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
            self.files.item(index).setText(f"Cancelled — {path.name}")
        self.statusBar().showMessage(
            "Cancelling after the current page; cleaning temporary outputs…"
        )
        self.cancel_button.setEnabled(False)

    def _filter_tools(self, text):
        from local_pdf_toolkit.ui.shell import category

        visible = []
        for index, spec in enumerate(self._operations):
            matches = text.lower() in spec.label.lower() and (
                self._category == "All tools" or category(spec) == self._category
            )
            self.operation_list.item(index).setHidden(not matches)
            if matches:
                visible.append(index)
        if self.operation_list.currentRow() not in visible:
            self.operation_list.setCurrentRow(visible[0] if visible else -1)
        if hasattr(self, "library"):
            self.library.reflow()
            self.library_count.setText(
                f"{len(visible)} tools"
                if visible
                else "No matching tools. Try another search or category."
            )
            self.library_title.setText(
                "Your document workspace." if self._category == "All tools" else self._category
            )
        if text:
            self.pages.setCurrentWidget(self.dashboard)

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
        self._sync_files()
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
                self.files.item(index).setText(f"Cancelled — {self._paths[index].name}")

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
