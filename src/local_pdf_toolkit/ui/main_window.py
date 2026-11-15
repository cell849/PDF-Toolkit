from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QSpinBox,
)

from local_pdf_toolkit.core.jobs import JobController
from local_pdf_toolkit.core.registry import ConverterRegistry
from local_pdf_toolkit.ui.workspace import WorkspaceBehavior


class MainWindow(WorkspaceBehavior, QMainWindow):
    def __init__(self, registry: ConverterRegistry) -> None:
        super().__init__()
        self._ux_ready = False
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
        self._init_workspace()

    def _show_library(self):
        if not self._active:
            if self._ux_ready:
                self._compatible_filter = None
                self._filter_tools(self.search.text())
            self.pages.setCurrentWidget(self.dashboard)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 980
        if hasattr(self, "sidebar") and compact != getattr(self, "_compact", False):
            self._compact = compact
            self.sidebar.setVisible(not compact)
            self.sidebar_action.blockSignals(True)
            self.sidebar_action.setChecked(not compact)
            self.sidebar_action.blockSignals(False)
        if hasattr(self, "form"):
            from PySide6.QtWidgets import QFormLayout

            policy = (
                QFormLayout.RowWrapPolicy.WrapAllRows
                if self.width() < 980
                else QFormLayout.RowWrapPolicy.WrapAllRows
            )
            self.form.setRowWrapPolicy(policy)
            if hasattr(self, "settings_action") and compact:
                self.settings_action.setChecked(False)

    def _open_preview(self):
        if self._active:
            return
        if self._current_spec() and self._current_spec().operation_id == "file.rename_copies":
            self._selection_changed()
            self._rename_preview.setFocus()
            return
        index = self.files.currentRow()
        if not 0 <= index < len(self._paths):
            self.statusBar().showMessage("Choose a file in the list to preview.")
            return
        from local_pdf_toolkit.ui.preview import PreviewDialog

        dialog = PreviewDialog(self._paths[index], self)
        dialog.exec()
        dialog.deleteLater()

    def _comparison_paths(self):
        index = self.files.currentRow()
        if not 0 <= index < len(self._paths):
            return None, ()
        outputs = tuple(
            path for path in self._results.get(index, ()) if path.suffix.lower() != ".json"
        )
        return self._paths[index], outputs

    def _open_comparison(self):
        if self._active:
            return
        source, outputs = self._comparison_paths()
        if source is None or not outputs:
            self.statusBar().showMessage("Choose a completed file to compare its output.")
            return
        from local_pdf_toolkit.ui.preview import ComparisonDialog

        dialog = ComparisonDialog(source, outputs, self)
        dialog.exec()
        dialog.deleteLater()

    def _sync_comparison(self, *_):
        _, outputs = self._comparison_paths()
        self.compare_button.setEnabled(bool(outputs) and not self._active)
        self.compare_button.setVisible(bool(outputs))
        if self._ux_ready:
            index = self.files.currentRow()
            selected = self._results.get(index, ())
            self.result_open.setVisible(bool(selected) and not self._active)
            self.result_open.setEnabled(bool(selected) and not self._active)
            self.result_open.setText("View report" if selected and not outputs else "Open result")

    def _open_report(self):
        import json

        from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout

        selected = self.files.currentRow()
        candidates = [selected] if selected >= 0 else list(reversed(self._results))
        report_path = next(
            (
                path
                for index in candidates
                for path in self._results.get(index, ())
                if path.suffix.lower() == ".json"
            ),
            None,
        )
        if report_path is None:
            self.statusBar().showMessage(
                "Choose a completed metadata-cleaning job to view its report."
            )
            return
        try:
            if report_path.stat().st_size > 65536:
                raise ValueError("Report too large")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                raise ValueError("Invalid report")
            categories = report.get("policy_categories", report.get("removed_categories", []))
            lines = [
                "CLEANING POLICY",
                str(report.get("policy", "")),
                "",
                *["• " + str(value) for value in categories],
                "",
                "IMPORTANT LIMITS",
                str(report.get("limits", "")),
            ]
            for index, inspection in enumerate(report.get("inspection", []), 1):
                lines.extend(["", f"FILE {index} ({inspection.get('format', 'Unknown')})"])
                lines.extend(
                    f"{key}: {value}" for key, value in inspection.get("counts", {}).items()
                )
                if not inspection.get("counts"):
                    lines.append("No fields detected in the supported structures.")
            if report.get("removed_category_counts"):
                lines.extend(["", "REMOVED CATEGORY COUNTS"])
                lines.extend(
                    f"{key.replace('_', ' ')}: {value}"
                    for key, value in report["removed_category_counts"].items()
                )
            comparison = report.get("comparison", [])
            if comparison:
                lines.extend(["", "BEFORE → AFTER"])
                lines.extend(
                    f"{row['category']}: {row['before']} → {row['after']}" for row in comparison
                )
            if "document_details" in report:
                from local_pdf_toolkit.ui.report_text import document_details_text

                lines = document_details_text(report["document_details"], report.get("limits", []))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            self.statusBar().showMessage(
                "Could not read the cleaning report. Check the output folder."
            )
            return
        dialog = QDialog(self)
        details = "document_details" in report
        dialog.setWindowTitle("Document details" if details else "Cleaning report")
        dialog.resize(620, 430)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        text.setAccessibleName("Document details" if details else "Cleaning policy and limitations")
        layout.addWidget(text)
        dialog.exec()

    def _appearance_changed(self, *_):
        from local_pdf_toolkit.ui.design import apply_theme

        apply_theme(self)

    def _select_tool(self, index):
        if self._active:
            return
        if self._ux_ready:
            self._suggest_tools = False
            self._compatible_filter = None
        self.operation_list.setCurrentRow(index)
        self.pages.setCurrentWidget(self.workspace)

    def _category_changed(self, index):
        from local_pdf_toolkit.ui.shell import CATEGORIES

        self._category = CATEGORIES[index] if index >= 0 else "All tools"
        self.pages.setCurrentWidget(self.dashboard)
        self._filter_tools(self.search.text())

    def _options(self, index):
        self._switch_document_context(index)
        if hasattr(self, "advanced_form"):
            while self.advanced_form.rowCount():
                self.advanced_form.removeRow(0)
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors = {}
        self.start_button.setEnabled(index >= 0 and not self._active)
        if index < 0:
            self.notice.clear()
            return
        spec = self._operations[index]
        privacy = spec.operation_id.startswith("metadata.")
        self.options_heading.setText(
            "Cleaning policy" if privacy and not spec.options else "Options"
        )
        self.report_button.setVisible(
            privacy or spec.operation_id in ("pdf.redact", "document.details")
        )
        self.report_button.setEnabled(any(self._results.values()))
        self.tool_title.setText(spec.label.replace(" / resize / compress", ""))
        self.tool_hint.setText(
            "Files are combined in the order below."
            if spec.input_mode == "multiple"
            else "Each file is processed separately. Originals stay untouched."
        )
        rename = spec.operation_id == "file.rename_copies"
        self.output_name.setEnabled(not rename and not self._active)
        self.output_name.setPlaceholderText(
            "Use naming options above" if rename else "Automatic name"
        )
        if rename:
            self.tool_hint.setText("Preview names, then save separate copies in the listed order.")
        elif spec.operation_id == "document.details":
            self.tool_hint.setText(
                "Inspect fonts, page sizes, encryption and attachments. "
                "Open the report after saving."
            )
        if privacy:
            formats = ", ".join(kind.value.upper() for kind in spec.input_formats)
            self.tool_hint.setText(
                f"Supported: {formats}. Separate copy and report. Personal content can remain."
            )
            if spec.operation_id == "metadata.inspect":
                self.tool_hint.setText(
                    "Inspect one file, or compare original then cleaned copy. Values stay masked."
                )
        for option in spec.options:
            if option.name == "target_kib":
                self._editors[option.name] = lambda: 0
                continue
            if option.name == "target_unit" and "target_value" in self._editors:
                continue
            if spec.operation_id == "pdf.redact" and option.name == "source_sha256":
                self._editors[option.name] = self._redaction_control.digest
                continue
            if option.name == "target_value":
                from local_pdf_toolkit.ui.controls import TargetSizeEditor

                unit = next(item for item in spec.options if item.name == "target_unit")
                widget = TargetSizeEditor(option.default, unit.default, unit.choices)
                getter = widget.amount.value
                self._editors[unit.name] = widget.unit.currentData
            elif option.name in ("quality", "resize_percent") or (
                option.name == "dpi" and not option.choices
            ):
                from local_pdf_toolkit.ui.controls import SliderNumber

                widget = SliderNumber(
                    option.minimum if option.minimum is not None else 1,
                    option.maximum if option.maximum is not None else 1200,
                    option.default,
                    option.label,
                    suffix="%" if option.name == "resize_percent" else "",
                    landmarks=(72, 96, 150, 200, 300, 600) if option.name == "dpi" else (),
                )
                getter = widget.value
            elif spec.operation_id == "pdf.redact" and option.name == "regions":
                from local_pdf_toolkit.ui.redaction import RedactionControl

                widget = RedactionControl(self)
                self._redaction_control = widget
                getter = widget.value
            elif option.choices:
                from local_pdf_toolkit.ui.controls import ChoiceBox

                widget = ChoiceBox()
                for choice in option.choices:
                    display = {
                        "lossless": "Lossless — keep text and vectors",
                        "rasterized": "Rebuild as page images",
                    }.get(choice, str(choice))
                    widget.addItem(display, choice)
                widget.setCurrentIndex(option.choices.index(option.default))
                getter = widget.currentData
            elif isinstance(option.default, bool):
                widget = QCheckBox()
                widget.setChecked(option.default)
                getter = widget.isChecked
            elif isinstance(option.default, int):
                from local_pdf_toolkit.ui.controls import NumericSpinBox

                widget = NumericSpinBox()
                widget.setRange(
                    option.minimum if option.minimum is not None else 0,
                    option.maximum if option.maximum is not None else 100,
                )
                widget.setValue(option.default)
                getter = widget.value
            elif isinstance(option.default, float):
                from local_pdf_toolkit.ui.controls import NumericDoubleSpinBox

                widget = NumericDoubleSpinBox()
                widget.setDecimals(4)
                widget.setRange(
                    option.minimum if option.minimum is not None else 0,
                    option.maximum if option.maximum is not None else 1_000_000,
                )
                widget.setValue(option.default)
                getter = widget.value
            else:
                widget = QLineEdit(str(option.default))
                if option.name == "password":
                    widget.setEchoMode(QLineEdit.EchoMode.Password)
                getter = widget.text
            widget.setToolTip(
                "Mark areas on the displayed PDF pages. All pages are rebuilt as images."
                if spec.operation_id == "pdf.redact" and option.name == "regions"
                else option.description
            )
            help_text = {
                "dpi": (
                    "Higher DPI creates more pixels and larger files. Try 150 for screen viewing "
                    "or 300 for print; type an exact value when needed."
                ),
                "quality": (
                    "Higher encoding quality preserves more detail but usually increases "
                    "file size. This is not a percentage of the original file size."
                ),
                "resize_percent": (
                    "50% halves both image dimensions. Aspect ratio is preserved; "
                    "this is different from keeping 50% of the file bytes."
                ),
                "allow_downscale": (
                    "Off preserves your chosen dimensions or DPI. If quality changes cannot reach "
                    "the target, no output is saved. Enable to allow smaller dimensions."
                ),
            }.get(option.name)
            if help_text:
                widget.setToolTip(help_text)
                widget.setAccessibleDescription(help_text)
            widget.setAccessibleName(option.label)
            basic = {
                "dpi",
                "quality",
                "width",
                "height",
                "resize_percent",
                "target_value",
                "allow_downscale",
                "mode",
                "pages",
                "password",
                "regions",
            }
            target_form = self.form if rename or option.name in basic else self.advanced_form
            display_label = option.label.replace(" (px, 0 = original)", " (px)").replace(
                " (0 = no target)", ""
            )
            if option.name in ("width", "height"):
                widget.setSpecialValueText("Original")
            target_form.addRow(display_label, widget)
            label = target_form.itemAt(
                target_form.rowCount() - 1, target_form.ItemRole.LabelRole
            ).widget()
            label.setWordWrap(True)
            for child in [
                widget,
                *widget.findChildren(QLineEdit),
                *widget.findChildren(QSpinBox),
                *widget.findChildren(QDoubleSpinBox),
                *widget.findChildren(QComboBox),
                *widget.findChildren(QCheckBox),
            ]:
                for signal in ("valueChanged", "currentIndexChanged", "textEdited", "toggled"):
                    if hasattr(child, signal):
                        getattr(child, signal).connect(self._settings_changed)
                        break
            self._editors[option.name] = getter
        self.notice.setText(" ".join(spec.limitations))
        self.advanced_toggle.setVisible(self.advanced_form.rowCount() > 0)
        self._restore_form_values()
        self._update_summary()
        self._selection_changed()

    def add_paths(self, paths):
        if self._active:
            return
        for path in paths:
            path = Path(path).absolute()
            if not path.is_file():
                self.statusBar().showMessage("Choose local files, not folders.")
                continue
            if path not in self._paths:
                self._paths.append(path)
                self.files.addItem(f"Ready — {path.name}")
                self.files.item(self.files.count() - 1).setToolTip(str(path))
                if self._ux_ready:
                    self._queue_inspection(path)
        self._sync_files()
        if self._paths:
            if self.files.currentRow() < 0:
                self.files.setCurrentRow(0)
            self.pages.setCurrentWidget(self.workspace)
            self._selection_changed()

    def dragEnterEvent(self, event):
        if not self._active and event.mimeData().hasUrls():
            self.drop_overlay.setGeometry(self.drop_overlay.parentWidget().rect())
            self.drop_overlay.show()
            self.drop_overlay.raise_()
            event.acceptProposedAction()

    def dropEvent(self, event):
        self._suggest_tools = self.pages.currentWidget() == self.dashboard
        self.add_paths(url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile())
        self.drop_overlay.hide()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.drop_overlay.hide()
        event.accept()

    def _choose_files(self):
        if self._active:
            return
        spec = self._current_spec()
        kinds = [kind.value for kind in spec.input_formats] if spec else []
        patterns = ["*." + kind for kind in kinds]
        if "jpeg" in kinds:
            patterns.append("*.jpg")
        if "tiff" in kinds:
            patterns.append("*.tif")
        filter_text = (
            f"Supported files ({' '.join(patterns)});;All files (*)"
            if patterns
            else "All files (*)"
        )
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", "", filter_text)
        self._suggest_tools = self.pages.currentWidget() == self.dashboard
        self.add_paths(paths)

    def _sync_files(self):
        self.files.setVisible(bool(self._paths))
        self.drop_hint.setVisible(not self._paths)
        for button in (
            self.up_button,
            self.down_button,
            self.remove_button,
            self.cancel_selected,
        ):
            button.setVisible(bool(self._paths))
        self.preview_button.setVisible(True)
        self.preview_button.setEnabled(bool(self._paths) and not self._active)
        spec = self._current_spec()
        for button in (self.up_button, self.down_button):
            button.setVisible(bool(spec and spec.input_mode == "multiple" and len(self._paths) > 1))
        self.retry_button.setVisible(bool(self._failed) and not self._active)
        self.cancel_selected.setVisible(self._active and bool(self._paths))
        self.file_heading.setText(f"Files · {len(self._paths)}" if self._paths else "Files")
        self._sync_comparison()
        self._update_summary()

    def _clear(self):
        if self._active:
            return
        if self._ux_ready:
            self._remember_file_change()
        self._paths.clear()
        self.files.clear()
        self._failed.clear()
        self._results.clear()
        self.report_button.setEnabled(False)
        self._sync_files()
        if self._ux_ready:
            self._selection_changed()
            self._set_result("ready", "Ready", "Add a file to get started.")

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
        self.progress.setVisible(active and self.pages.currentWidget() == self.workspace)
        if self._ux_ready:
            self.document_preview.set_busy(active)
        for widget in (
            self.add_button,
            self.clear_button,
            self.operation_list,
            self.options_widget,
            self.destination,
            self.output_name,
            self.browse,
            self.start_button,
            self.up_button,
            self.down_button,
            self.remove_button,
            self.retry_button,
            self.search,
            self.navigation,
            self.back_button,
            self.preview_button,
        ):
            widget.setEnabled(not active)
        self.cancel_button.setEnabled(active)
        self.cancel_button.setVisible(active)
        self.cancel_selected.setVisible(active and bool(self._paths))
        self.start_button.setEnabled(not active and self.operation_list.currentRow() >= 0)
        if self._current_spec() and self._current_spec().operation_id == "file.rename_copies":
            self.output_name.setEnabled(False)
        self._sync_comparison()

    def _start(self):
        if self._active or (not self._retrying and self.operation_list.currentRow() < 0):
            return
        if (
            not self._paths
            or not self.destination.text()
            or not Path(self.destination.text()).is_dir()
        ):
            self._retrying = False
            self._set_result(
                "error",
                "Choose an output folder" if self._paths else "Add a file",
                "Add compatible input files and choose an existing output folder.",
            )
            self.statusBar().showMessage("Add input files and choose an existing output folder.")
            return
        if not self._guard_run():
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
        if self._converter.spec.operation_id == "pdf.redact":
            from local_pdf_toolkit.ui.redaction import signature

            if self._retrying:
                valid = signature(self._paths) == getattr(self, "_redaction_source", None)
            else:
                valid = self._options_values.get("regions", "[]") != "[]"
                self._redaction_source = signature(self._paths)
            if len(self._paths) != 1 or not valid:
                self.statusBar().showMessage("Add exactly one unchanged PDF and mark areas first.")
                self._retrying = False
                return
        spec = self._converter.spec
        indices = (
            sorted(self._failed)
            if self._retrying and spec.input_mode != "multiple"
            else list(range(len(self._paths)))
        )
        preflight = dict(self._preflight_errors)
        if preflight and spec.input_mode == "multiple":
            self._retrying = False
            self._failed.update(preflight)
            self._errors.update(preflight)
            self._batch_finished_feedback()
            return
        indices = [
            index
            for index in indices
            if index not in preflight and index not in self._pre_cancelled
        ]
        self._retrying = False
        self._failed = set(preflight) | self._pre_cancelled
        if self._converter.spec.input_mode == "multiple":
            self._pending = (
                [(indices[0], tuple(self._paths[i] for i in indices))] if indices else []
            )
            self._batch_indices = indices
        else:
            self._pending = [(i, self._paths[i]) for i in indices]
            self._batch_indices = []
        self._stopping = False
        self._cancelled = set(self._pre_cancelled)
        self._pre_cancelled.clear()
        self._errors = preflight
        self._run_values = self._current_values()
        self._set_active(True)
        self._set_result("working", "Processing", "Original files stay unchanged.")
        for index in indices:
            self._results.pop(index, None)
            self.report_button.setEnabled(False)
            self.files.item(index).setText(f"Queued — {self._paths[index].name}")
        self._next()

    def _next(self):
        if not self._pending or self._stopping:
            self._pending.clear()
            self._set_active(False)
            self._batch_finished_feedback()
            if self._closing:
                self.close()
            return
        self._row, path = self._pending.pop(0)
        self._group = self._batch_indices or [self._row]
        for index in self._group:
            self.files.item(index).setText(f"Running — {self._paths[index].name}")
        self.progress.setRange(0, 0)
        try:
            converter = self._converter
            base = self.output_name.text().strip()
            if base and converter.spec.operation_id != "file.rename_copies":
                from local_pdf_toolkit.converters.named_output import (
                    NamedOutputConverter,
                    normalize_base_name,
                )

                if len(self._paths) > 1 and converter.spec.input_mode != "multiple":
                    base = normalize_base_name(base, converter.spec.output_formats)
                    base += f"-{self._row + 1}"
                converter = NamedOutputConverter(converter, base)
            self.jobs.start(converter, path, self._output_directory, self._options_values)
        except Exception as exc:
            from local_pdf_toolkit.core.errors import ConversionError

            if isinstance(exc, ConversionError):
                self._finished((), (exc.code.value, str(exc)))
            else:
                self._finished((), ("conversion_failed", "Could not start conversion process."))

    def _progress(self, progress):
        self.progress.setRange(0, progress.total or 0)
        self.progress.setValue(progress.completed)
        self.statusBar().showMessage(
            f"Processed {progress.completed} of {progress.total}"
            if progress.total
            else "Processing…"
        )

    def _finished(self, paths, error):
        for position, index in enumerate(self._group):
            message = f"Done — {len(paths)} outputs — {self._paths[index].name}"
            if error:
                message = f"Failed — {self._paths[index].name}"
                self._failed.add(index)
                self._errors[index] = error[1]
                if error[0] == "cancelled":
                    self._cancelled.add(index)
            else:
                self._results[index] = (
                    (paths[position],) if self._tool_id == "file.rename_copies" else tuple(paths)
                )
                configuration = dict(self._run_values)
                configuration["_source_signature"] = self._signature(self._paths[index])
                self._result_settings[(self._tool_id, self._paths[index])] = configuration
            self.files.item(index).setText(message)
            self.files.item(index).setToolTip(message + "\n" + "\n".join(map(str, paths)))
        self.report_button.setEnabled(any(self._results.values()))
        self._sync_comparison()
        self._selection_changed()
        QTimer.singleShot(0, self._next)

    def _cancel(self):
        self._stopping = True
        self._requested_start = False
        if self._ux_ready and self._probe_jobs.running:
            self._probe_jobs.cancel()
        self._set_result(
            "cancelled", "Cancelling…", "Waiting for the worker and cleaning temporary outputs."
        )
        self.jobs.cancel()
        for index, path in self._pending:
            self._failed.add(index)
            self._cancelled.add(index)
            self.files.item(index).setText(f"Cancelled — {path.name}")
        self.statusBar().showMessage(
            "Cancelling after the current page; cleaning temporary outputs…"
        )
        self.cancel_button.setEnabled(False)
        self._resource_idle()

    def _filter_tools(self, text):
        from local_pdf_toolkit.ui.shell import category, matches_search

        visible = []
        for index, spec in enumerate(self._operations):
            compatible = not getattr(
                self, "_compatible_filter", None
            ) or self._compatible_filter <= {kind.value for kind in spec.input_formats}
            matches = (
                compatible
                and matches_search(spec, text)
                and (self._category == "All tools" or category(spec) == self._category)
            )
            self.operation_list.item(index).setHidden(not matches)
            if matches:
                visible.append(index)
        exact = next(
            (i for i in visible if self._operations[i].label.lower() == text.lower()), None
        )
        if exact is not None:
            self.operation_list.setCurrentRow(exact)
        elif self.operation_list.currentRow() not in visible:
            self.operation_list.setCurrentRow(visible[0] if visible else -1)
        if hasattr(self, "library"):
            self.library.reflow()
            self.library_count.setText(
                f"{len(visible)} tools"
                if visible
                else "No matching tools. Try another search or category."
            )
            self.library_title.setText(self._category)
        if text:
            self.pages.setCurrentWidget(self.dashboard)

    def _move(self, delta):
        index = self.files.currentRow()
        target = index + delta
        if self._active or index < 0 or not 0 <= target < len(self._paths):
            return
        self._remember_file_change()
        old_paths = list(self._paths)
        self._paths[index], self._paths[target] = self._paths[target], self._paths[index]
        item = self.files.takeItem(index)
        self.files.insertItem(target, item)
        self.files.setCurrentRow(target)
        self._remap_edited_results(old_paths)
        self._sync_comparison()

    def _remove(self):
        index = self.files.currentRow()
        if self._active or index < 0:
            return
        self._remember_file_change()
        old_paths = list(self._paths)
        self._paths.pop(index)
        self.files.takeItem(index)
        self._remap_edited_results(old_paths)
        self._sync_files()
        self._sync_comparison()

    def _retry(self):
        if self._active or not self._failed:
            return
        self._last_config = (
            self.registry.get(self._current_spec().operation_id),
            {name: getter() for name, getter in self._editors.items()},
            Path(self.destination.text()).absolute(),
        )
        self._retrying = True
        self._start()

    def _cancel_one(self):
        if not self._active:
            return
        index = self.files.currentRow()
        if index < 0:
            return
        if self._requested_start and not self.jobs.running:
            if self._current_spec().input_mode == "multiple":
                self._cancel()
                return
            self._pre_cancelled.add(index)
            self._failed.add(index)
            self._cancelled.add(index)
            self.files.item(index).setText(f"Cancelled — {self._paths[index].name}")
        elif index in self._group:
            self.jobs.cancel()
        elif any(i == index for i, _ in self._pending):
            self._pending = [(i, path) for i, path in self._pending if i != index]
            self._failed.add(index)
            self._cancelled.add(index)
            if index >= 0:
                self.files.item(index).setText(f"Cancelled — {self._paths[index].name}")

    def _open_result(self, item=None):
        if item is not None:
            self.files.setCurrentItem(item)
        self._open_selected_result()

    def closeEvent(self, event):
        if self._active:
            self._closing = True
            self._cancel()
            event.ignore()
        else:
            self._closing = True
            if not self._close_workspace():
                event.ignore()
            else:
                event.accept()
