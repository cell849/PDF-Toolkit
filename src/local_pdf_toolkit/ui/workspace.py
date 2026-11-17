"""Session-only document state, inspection and persistent task feedback."""

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMenu, QPushButton, QVBoxLayout

from local_pdf_toolkit.core.jobs import JobController


class WorkspaceBehavior:
    def _init_workspace(self):
        from local_pdf_toolkit.ui.document_preview import DocumentPreview
        from local_pdf_toolkit.ui.icons import app_icon

        self.setWindowIcon(app_icon())
        self._suggest_tools = False
        self._compatible_filter = None
        self._carryover = set()
        self._contexts = {}
        self._context_values = {}
        self._context_names = {}
        self._tool_id = (
            self._operations[self.operation_list.currentRow()].operation_id
            if self._operations
            else None
        )
        self._records = {}
        self._undo = []
        self._errors = {}
        self._cancelled = set()
        self._pre_cancelled = set()
        self._run_values = None
        self._result_settings = {}
        self._requested_start = False
        self._probe_temp = tempfile.TemporaryDirectory(prefix="toolkit-inspection-")
        self._probe_jobs = JobController(self)
        self._probe_jobs.finished.connect(self._inspection_finished)
        self._probe_queue = []
        self._probe_path = None
        self.document_preview = DocumentPreview(self)
        self._rename_preview = None
        self._page_organizer = None
        self.preview_host.layout().addWidget(self.document_preview)
        self.document_preview.compare_requested.connect(self._open_comparison)
        self.document_preview.idle.connect(self._resource_idle)
        if hasattr(self.document_preview, "thumbnail_ready"):
            self.document_preview.thumbnail_ready.connect(self._thumbnail_ready)
        self.files.currentRowChanged.connect(self._selection_changed)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._file_menu)
        from local_pdf_toolkit.core.recovery import has_recovery_records

        recovery_hint = has_recovery_records()
        if recovery_hint:
            self.recovery_action.setText("Review temporary jobs from previous sessions…")
            self._show_status(
                "Temporary job records found. Review them in Tools → Clean up interrupted jobs."
            )
        self._preferences = QSettings("LocalPDFToolkit", "Desktop")
        geometry = self._preferences.value("windowGeometry")
        if geometry:
            self.restoreGeometry(geometry)
        library_sizes = self._preferences.value("librarySizes")
        if library_sizes:
            self.library_splitter.setSizes([int(size) for size in library_sizes])
        sizes = self._preferences.value("workspaceSizes")
        if sizes:
            self.workspace_splitter.setSizes([int(size) for size in sizes])
        self._ux_ready = True
        self.cancel_button.hide()
        view_menu = self.view_menu
        if view_menu is not None:
            size_menu = view_menu.addMenu("Text size")
            group = QActionGroup(self)
            for percent in (100, 125, 150, 200):
                action = QAction(f"{percent}%", self)
                action.setCheckable(True)
                group.addAction(action)
                action.setChecked(percent == int(self._preferences.value("textSize", 100)))
                action.triggered.connect(
                    lambda checked=False, value=percent: self._set_text_size(value)
                )
                size_menu.addAction(action)
        self._set_text_size(int(self._preferences.value("textSize", 100)))
        stored_sidebar = self._preferences.value("sidebarCollapsed")
        if stored_sidebar is not None:
            self._sidebar_user_choice = str(stored_sidebar).lower() == "true"
        self._set_sidebar_collapsed(
            self.width() < 980 if self._sidebar_user_choice is None else self._sidebar_user_choice,
            remember=False,
        )
        self.settings_action.setChecked(True)
        self._restore_form_values()
        self._set_result(
            "ready",
            "Ready",
            "Temporary job records found. Use Tools → Review temporary jobs from previous sessions."
            if recovery_hint
            else "",
        )
        self._update_summary()

    def _set_text_size(self, percent):
        from local_pdf_toolkit.ui.design import apply_theme

        value = percent if percent in (100, 125, 150, 200) else 100
        self.setProperty("textScale", value / 100)
        self._preferences.setValue("textSize", value)
        apply_theme(self)
        self._set_sidebar_collapsed(self.navigation.collapsed, remember=False)

    def _current_spec(self):
        index = self.operation_list.currentRow()
        return self._operations[index] if index >= 0 else None

    def _switch_document_context(self, index):
        if not self._ux_ready:
            return
        spec = self._operations[index] if index >= 0 else None
        new_id = spec.operation_id if spec else None
        if new_id == self._tool_id:
            return
        self._contexts[self._tool_id] = (
            list(self._paths),
            dict(self._results),
            set(self._failed),
            dict(self._errors),
        )
        self._context_values[self._tool_id] = {key: get() for key, get in self._editors.items()}
        self._context_names[self._tool_id] = self.output_name.text()
        self.output_name.setText(self._context_names.get(new_id, ""))
        previous = list(self._paths)
        if new_id in self._contexts:
            paths, results, failed, errors = self._contexts[new_id]
        else:
            allowed = {kind.value for kind in spec.input_formats} if spec else set()
            paths = [
                path for path in previous if self._records.get(path, {}).get("format") in allowed
            ]
            results, failed, errors = {}, set(), {}
        self._paths = list(paths)
        self._results, self._failed, self._errors = dict(results), set(failed), dict(errors)
        self._tool_id = new_id
        self.batch_filter.setCurrentIndex(0)
        self._cancelled.clear()
        self._undo.clear()
        self._requested_start = False
        self._retrying = False
        self._run_values = None
        if hasattr(self, "_last_config"):
            del self._last_config
        self._rebuild_files()
        message = "Choose files supported by this tool." if previous and not paths else ""
        self._set_result("ready", "Ready", message)
        self._sync_files()
        self._selection_changed()

    @staticmethod
    def _signature(path):
        try:
            value = path.stat()
            return value.st_size, value.st_mtime_ns
        except OSError:
            return None

    def _queue_inspection(self, path):
        signature = self._signature(path)
        if path in self._records and self._records[path].get("signature") == signature:
            return
        self._records.pop(path, None)
        if path not in self._probe_queue and path != self._probe_path:
            self._probe_queue.append(path)
        self._next_inspection()

    def _next_inspection(self):
        if self._probe_jobs.running or self._closing:
            return
        if not self._probe_queue:
            if self._requested_start:
                QTimer.singleShot(0, self._resume_requested_start)
            return
        from local_pdf_toolkit.converters.file_probe import FileProbeConverter

        self._probe_path = self._probe_queue.pop(0)
        self._probe_signature = self._signature(self._probe_path)
        self._inspection_progress()
        try:
            self._probe_jobs.start(
                FileProbeConverter(), self._probe_path, Path(self._probe_temp.name), {"formats": ""}
            )
        except Exception:
            self._inspection_finished((), ("invalid_input", "Could not inspect this file."))

    def _inspection_finished(self, paths, error):
        path = self._probe_path
        try:
            info = (
                json.loads(paths[0].read_text())
                if paths and not error
                else {
                    "ready": False,
                    "reason": error[1] if error else "Inspection failed.",
                    "format": "",
                }
            )
        except (OSError, ValueError, TypeError):
            info = {"ready": False, "reason": "Could not read inspection results.", "format": ""}
        for report in paths:
            try:
                report.unlink(missing_ok=True)
            except OSError:
                pass
        if self._signature(path) == self._probe_signature and not (
            error and error[0] == "cancelled"
        ):
            info["signature"] = self._probe_signature
            self._records[path] = info
        self._probe_path = None
        self._inspection_progress()
        if path in self._carryover:
            self._carryover.discard(path)
            ready, _ = self._file_ready(path)
            if ready is False and path in self._paths:
                self._paths.remove(path)
                self._sync_files()
                self._set_result(
                    "ready",
                    "Choose another file",
                    "The previous file is not compatible with this tool.",
                )
        self._rebuild_files(changed_path=path)
        self._selection_changed()
        self._update_summary()
        if (
            self._suggest_tools
            and self._paths
            and all(path in self._records for path in self._paths)
        ):
            self._suggest_tools = False
            kinds = {self._records[path].get("format") for path in self._paths}
            if None not in kinds and all(self._records[path].get("ready") for path in self._paths):
                self._compatible_filter = kinds
                self.search.clear()
                self.navigation.setCurrentRow(0)
                self._category = "All tools"
                self._filter_tools(self.search.text())
                self.pages.setCurrentWidget(self.dashboard)
                self.library_title.setText("Choose what to do with your files.")
        if (
            not self._active
            and self._paths
            and not self._results
            and not self._failed
            and not self._probe_queue
            and self._file_ready(self._paths[self.files.currentRow()])[0] is True
        ):
            self._set_result(
                "ready", "Ready to process", "Choose settings, then use the action below."
            )
        if self._closing or self._stopping:
            self._requested_start = False
            if not self.jobs.running:
                self._set_active(False)
            if not self._closing and self._stopping:
                self._set_result(
                    "cancelled", "Cancelled", "Inspection stopped. Original files unchanged."
                )
            self._resource_idle()
        else:
            self._next_inspection()

    def _inspection_progress(self):
        pending = set(getattr(self, "_probe_queue", ()))
        active = getattr(self, "_probe_path", None)
        if active is not None:
            pending.add(active)
        remaining = sum(path in pending for path in self._paths)
        total = len(self._paths)
        self.file_heading.setText(
            f"Files · {total - remaining} of {total} inspected"
            if remaining
            else f"Files · {total}"
            if total
            else "Files"
        )

    def _file_ready(self, path):
        spec = self._current_spec()
        info = self._records.get(path)
        if not info or info.get("signature") != self._signature(path):
            return None, "Inspecting file…"
        if (
            info.get("error_code") == "password_required"
            and spec
            and spec.operation_id in ("pdf.unlock", "document.details")
        ):
            if spec.operation_id == "document.details":
                return True, "Encryption details are available; document contents remain locked."
            password = self._editors.get("password", lambda: "")()
            return (
                (True, "Password will be verified during processing.")
                if password
                else (False, "Enter the PDF password in Options to unlock it.")
            )
        if not info.get("ready"):
            return False, info.get("reason", "This file cannot be processed.")
        if spec and info.get("format") not in {kind.value for kind in spec.input_formats}:
            return False, "This file type is not supported by the selected tool."
        return True, "Ready"

    def _rebuild_files(self, changed_path=None):
        selected = self.files.currentRow()
        changed_index = self._paths.index(changed_path) if changed_path in self._paths else None
        incremental = (
            changed_index is not None
            and self.files.count() == len(self._paths)
            and self.files.item(changed_index).data(Qt.ItemDataRole.UserRole) == changed_path
        )
        icons = {
            self.files.item(i).data(Qt.ItemDataRole.UserRole): self.files.item(i).icon()
            for i in (() if incremental else range(self.files.count()))
        }
        self.files.blockSignals(True)
        if not incremental:
            self.files.clear()
        indices = (changed_index,) if incremental else range(len(self._paths))
        for index in indices:
            path = self._paths[index]
            info = self._records.get(path, {})
            ready, reason = self._file_ready(path)
            state = (
                "Failed"
                if index in self._failed
                else "Done"
                if index in self._results
                else "Ready"
                if ready
                else "Inspecting"
                if ready is None
                else "Unavailable"
            )
            if index in self._cancelled:
                state = "Cancelled"
            details = (
                f"{(info.get('format') or path.suffix.lstrip('.')).upper()} · "
                f"{(info.get('bytes') or 0):,} bytes"
                if info
                else reason
            )
            if info.get("unit") != "px" and info.get("pages"):
                details += f" · {info['pages']} pages"
            elif info.get("width") and info.get("height"):
                details += f" · {info['width']} × {info['height']} {info.get('unit', 'px')}"
            text = f"{state} — {path.name}\n{details}"
            if incremental:
                self.files.item(index).setText(text)
            else:
                self.files.addItem(text)
            self.files.item(index).setToolTip(
                path.name + "\n" + self._errors.get(index, reason) + "\n" + details
            )
            self.files.item(index).setData(Qt.ItemDataRole.UserRole, path)
            self.files.item(index).setSizeHint(QSize(0, 58))
            if path in icons:
                self.files.item(index).setIcon(icons[path])
        if self._paths:
            self.files.setCurrentRow(min(max(selected, 0), len(self._paths) - 1))
        self.files.blockSignals(False)
        self._apply_batch_filter()

    def _apply_batch_filter(self):
        if not self._ux_ready:
            return
        selected = self.batch_filter.currentData()
        counts = {"all": len(self._paths), "failed": 0, "saved": 0, "pending": 0, "cancelled": 0}
        first = None
        for index in range(self.files.count()):
            state = (
                "cancelled"
                if index in self._cancelled
                else "failed"
                if index in self._failed
                else "saved"
                if index in self._results
                else "pending"
            )
            counts[state] += 1
            show = selected == "all" or selected == state
            self.files.item(index).setHidden(not show)
            if show and first is None:
                first = index
        self.batch_filter.setVisible(len(self._paths) > 1)
        self.batch_filter.blockSignals(True)
        for index, title in enumerate(("All files", "Failed", "Saved", "Pending", "Cancelled")):
            key = self.batch_filter.itemData(index)
            self.batch_filter.setItemText(index, f"{title} · {counts[key]}")
        self.batch_filter.blockSignals(False)
        current = self.files.currentItem()
        if current is not None and current.isHidden():
            self.files.setCurrentRow(first if first is not None else -1)
        elif current is None and first is not None:
            self.files.setCurrentRow(first)

    def _selection_changed(self, *_):
        if not self._ux_ready:
            return
        index = self.files.currentRow()
        if (
            len(self._paths) > 1
            and 0 <= index < len(self._paths)
            and (index in self._results or index in self._failed)
        ):
            path = self._paths[index]
            outcome = self._errors.get(index) or (
                self._saved_summary(index) if index in self._results else self._file_ready(path)[1]
            )
            self.selected_outcome.setText(f"{path.name}\n{outcome}")
            self.selected_outcome.show()
        else:
            self.selected_outcome.hide()
        rename = bool(self._current_spec() and self._tool_id == "file.rename_copies")
        organizing = self._tool_id == "pdf.organize_visual"
        self.document_preview.setVisible(not rename and not organizing)
        if self._page_organizer is not None:
            self._page_organizer.setVisible(organizing)
            self._page_organizer.set_busy(self._active or not organizing)
            if organizing:
                self.document_preview.set_document(None)
                self._page_organizer.set_sources(self._paths)
                self.preview_button.setText("Pages")
                self._update_summary()
                return
        self.preview_button.setText("Names" if rename else "Preview")
        if rename and self._rename_preview is None:
            from local_pdf_toolkit.ui.rename_preview import RenamePreview

            self._rename_preview = RenamePreview(self)
            self.preview_host.layout().addWidget(self._rename_preview)
        if self._rename_preview is not None:
            self._rename_preview.setVisible(rename)
        if rename:
            self.document_preview.set_document(None)
            self._rename_preview.update_plan(
                self._paths, {name: getter() for name, getter in self._editors.items()}
            )
            self._rename_preview.table.selectRow(self.files.currentRow())
            return
        index = self.files.currentRow()
        path = self._paths[index] if 0 <= index < len(self._paths) else None
        outputs = self._results.get(index, ())
        saved = self._result_settings.get((self._tool_id, path), self._run_values)
        stale = bool(outputs and saved != self._current_values())
        ready, reason = self._file_ready(path) if path else (False, "")
        if not self._active:
            self.document_preview.empty_message.setText(
                "Add a file to preview"
                if path is None
                else "Inspecting file…"
                if ready is None
                else "Preview unavailable for this file."
            )
            self.document_preview.set_document(
                path if ready else None,
                tuple(
                    p
                    for p in outputs
                    if p.suffix.lower() != ".json"
                    and not (self._tool_id == "pdf.compare" and p.suffix.lower() == ".txt")
                ),
                stale,
            )
        if path and ready is False and not self._active:
            self._set_result("error", "Choose a compatible file", reason)
        if index in self._errors and index not in self._cancelled and not self._active:
            self._set_result(
                "partial" if self._results else "error",
                f"{len(self._results)} saved · {len(self._failed)} failed"
                if self._results
                else "Processing failed",
                self._errors[index],
            )
        if index in self._results and not self._active and not self._failed:
            self.result_detail.setText(self._saved_summary(index))
        self._sync_comparison()

    def _thumbnail_ready(self, pixmap):
        item = self.files.currentItem()
        if item is not None:
            thumbnail = pixmap.scaled(
                48,
                48,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            item.setIcon(QIcon(thumbnail))

    def _show_status(self, message):
        self.feedback.setText(message)
        self.feedback.setVisible(
            self.pages.currentWidget() == self.workspace
            and bool(message)
            and message != self.result_title.text()
        )

    def _set_result(self, state, title, detail):
        if not self._ux_ready:
            return
        self.result_banner.setProperty("state", state)
        self.result_banner.style().unpolish(self.result_banner)
        self.result_banner.style().polish(self.result_banner)
        self.result_title.setText(title)
        self.feedback.setText(title)
        self.feedback.hide()
        self.result_detail.setText(detail)
        self.result_retry.setVisible(bool(self._failed) and not self._active)
        self.result_retry.setText(
            "Retry cancelled"
            if self._failed and self._failed <= self._cancelled
            else "Retry failed"
        )
        self.result_adjust.setVisible(state in ("error", "partial"))
        self._error_action = (
            "rename"
            if "already exists" in detail.lower()
            else "folder"
            if title == "Choose an output folder"
            else "options"
        )
        self.result_adjust.setText(
            "Save with another name"
            if self._error_action == "rename"
            else "Choose folder"
            if self._error_action == "folder"
            else "Adjust options"
        )
        self.result_open.setVisible(bool(self._results) and not self._active)
        self._sync_comparison()

    def _batch_finished_feedback(self):
        self._rebuild_files()
        self.progress.setRange(0, 1)
        self.progress.setValue(0 if self._failed or self._stopping else 1)
        saved, failed, cancelled = (
            len(self._results),
            len(self._failed - self._cancelled),
            len(self._cancelled),
        )
        if failed:
            detail = next(
                (message for i, message in self._errors.items() if i not in self._cancelled),
                "Adjust the settings or select another file.",
            )
            if not saved:
                detail += " No output saved."
            self._set_result(
                "partial" if saved else "error",
                f"{saved} saved · {failed} failed" if saved else "Processing failed",
                detail,
            )
        elif cancelled or self._stopping:
            self._set_result(
                "cancelled",
                "Cancelled",
                f"{saved} files saved. Remaining work was cancelled; temporary outputs cleaned up.",
            )
        elif saved:
            self._set_result("success", "Saved successfully", self._saved_summary())
        self._selection_changed()

    @staticmethod
    def _display_bytes(size):
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1000 or unit == "GB":
                return f"{size:,.0f} B" if unit == "B" else f"{size:,.2f} {unit}"
            size /= 1000

    def _saved_summary(self, selected=None):
        indices = [selected] if selected is not None else list(self._results)
        sources = set()
        outputs = set()
        configs = []
        spec = self._current_spec()
        for index in indices:
            if index not in self._results or not 0 <= index < len(self._paths):
                continue
            source = self._paths[index]
            sources.add(source)
            outputs.update(self._results[index])
            configs.append(self._result_settings.get((self._tool_id, source), {}))
        if spec and spec.input_mode == "multiple" and self._tool_id != "file.rename_copies":
            sources = set(self._paths)
        # Sidecar reports are excluded from conversion size comparisons; report-only
        # tools report their saved report size instead of pretending to compress inputs.
        documents = {p for p in outputs if p.suffix.lower() != ".json"}
        try:
            output_size = sum(p.stat().st_size for p in (documents or outputs))
        except OSError:
            return "Saved output is no longer available."
        if not documents:
            return f"Report saved · {self._display_bytes(output_size)}. Original files unchanged."
        if self._tool_id == "pdf.compare":
            return (
                f"Comparison saved · {self._display_bytes(output_size)}\n"
                "Open the PDF for highlighted pages; the text report is in the output folder. "
                "Pages are matched by page number. Originals unchanged."
            )
        sizes = [self._records.get(p, {}).get("bytes") for p in sources]
        before = sum(sizes) if sizes and all(isinstance(n, int) and n > 0 for n in sizes) else 0
        text = f"Saved · {self._display_bytes(output_size)}"
        if before:
            delta = (before - output_size) / before * 100
            change = f"{abs(delta):.1f}% {'smaller' if delta >= 0 else 'larger'}"
            text += f" · Original {self._display_bytes(before)} · {change}"
        if self._tool_id == "pdf.compress" and any(c.get("mode") == "rasterized" for c in configs):
            text += "\nPages converted to images; selectable text, links and forms removed."
        elif self._tool_id == "image.compare_formats":
            try:
                text += (
                    "\n"
                    + " · ".join(
                        f"{p.suffix[1:].upper()}: {self._display_bytes(p.stat().st_size)}"
                        for p in sorted(documents)
                    )
                    + "\nUse Compare to inspect each candidate. All candidates are saved."
                )
            except OSError:
                text += "\nSome candidates are no longer available."
        elif self._tool_id == "file.rename_copies":
            text += "\nByte-identical copies; metadata retained."
        text += "\nOriginal files unchanged."
        return text

    def _current_values(self):
        values = {key: get() for key, get in self._editors.items()}
        values["_output_name"] = self.output_name.text().strip()
        index = self.files.currentRow()
        if 0 <= index < len(self._paths):
            values["_source_signature"] = self._signature(self._paths[index])
        spec = self._current_spec()
        if spec and spec.operation_id == "file.rename_copies":
            values["_output_name"] = ""
        if spec and spec.input_mode == "multiple":
            values["_inputs"] = tuple(str(path) for path in self._paths)
        return values

    def _restore_form_values(self):
        if not self._ux_ready:
            return
        values = self._context_values.get(self._tool_id, {})
        if not values and hasattr(self, "_preferences"):
            unit = self._preferences.value("preferredUnit", "KiB")
            values = {"target_unit": unit}
        from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

        for form in (self.form, self.advanced_form):
            for row in range(form.rowCount()):
                widget = form.itemAt(row, form.ItemRole.FieldRole).widget()
                # Composite controls expose their numerical/choice children.
                children = [
                    widget,
                    *widget.findChildren(QSpinBox),
                    *widget.findChildren(QDoubleSpinBox),
                    *widget.findChildren(QComboBox),
                ]
                for key, getter in self._editors.items():
                    owner = getattr(getter, "__self__", None)
                    if key not in values or owner not in children:
                        continue
                    value = values[key]
                    if isinstance(owner, QComboBox):
                        position = owner.findData(value)
                        if position >= 0:
                            owner.setCurrentIndex(position)
                    elif hasattr(owner, "number"):
                        owner.number.setValue(value)
                    elif isinstance(owner, QSpinBox | QDoubleSpinBox):
                        owner.setValue(value)
                    elif isinstance(owner, QCheckBox):
                        owner.setChecked(value)
                    elif isinstance(owner, QLineEdit) and key != "password":
                        owner.setText(str(value))

    def _settings_changed(self, *_):
        if not self._ux_ready:
            return
        index = self.files.currentRow()
        path = self._paths[index] if 0 <= index < len(self._paths) else None
        saved = self._result_settings.get((self._tool_id, path), self._run_values)
        self.document_preview.set_stale(
            bool(index in self._results and saved != self._current_values())
        )
        self._update_summary()
        for section in (self.options_section, self.advanced_section):
            if section.popup.isVisible():
                section._toggle(True)

    def _update_summary(self):
        if not self._ux_ready:
            return
        values = {key: get() for key, get in self._editors.items()}
        spec = self._current_spec()
        parts = []
        rename = bool(spec and spec.operation_id == "file.rename_copies")
        if rename and self._rename_preview is not None:
            self._rename_preview.update_plan(self._paths, values)
        if values.get("width") or values.get("height"):
            parts.append(
                f"Fit within {values.get('width') or 'original'} × "
                f"{values.get('height') or 'original'} px"
            )
        if values.get("resize_percent", 100) != 100:
            parts.append(f"Resize to {values['resize_percent']}% dimensions")
        if values.get("dpi") and values.get("mode") != "lossless":
            parts.append(f"{values['dpi']} DPI")
            index = self.files.currentRow()
            path = self._paths[index] if 0 <= index < len(self._paths) else None
            info = self._records.get(path, {})
            if info.get("unit") == "pt" and info.get("width") and info.get("height"):
                import math

                width = math.ceil(info["width"] * values["dpi"] / 72)
                height = math.ceil(info["height"] * values["dpi"] / 72)
                parts.append(f"Selected page: {width:,} × {height:,} px")
        if values.get("quality") and values.get("mode") != "lossless":
            parts.append(f"Quality {values['quality']}")
        amount = values.get("target_value", 0)
        if amount:
            unit = values.get("target_unit", "KiB")
            parts.append(
                f"Keep {amount:g}% of original bytes"
                if unit == "percent"
                else f"Under {amount:g} {unit}"
            )
            if unit == "percent" and self._paths:
                total = sum((self._records.get(path, {}).get("bytes") or 0) for path in self._paths)
                parts.append(f"Target total ≤ {int(total * amount / 100):,} bytes")
        if amount and "allow_downscale" in values and values.get("mode") != "lossless":
            parts.append(
                "May reduce resolution" if values["allow_downscale"] else "Preserve resolution"
            )
        if spec and spec.operation_id == "pdf.compress":
            lossless = values.get("mode") == "lossless"
            parts.insert(
                0,
                "Lossless — keeps text and vectors"
                if lossless
                else "Page images — selectable text and interactivity removed",
            )
        for key, (editor, caption) in self._option_rows.items():
            visible = not (
                (
                    spec
                    and spec.operation_id == "pdf.compress"
                    and values.get("mode") == "lossless"
                    and key in ("dpi", "quality")
                )
                or (key == "allow_downscale" and (not amount or values.get("mode") == "lossless"))
            )
            if (
                spec
                and spec.operation_id == "pdf.normalize_pages"
                and key in ("custom_width", "custom_height", "units")
            ):
                visible = values.get("paper") == "custom"
            editor.setVisible(visible)
            caption.setVisible(visible)
            if key == "target_value":
                editor.amount.setToolTip("")
                editor.unit.setToolTip("")
        if spec and spec.operation_id == "metadata.inspect":
            parts.insert(0, "Inspect one file, or compare original then cleaned copy")
        elif rename:
            parts.insert(0, f"Save {len(self._paths)} numbered copies in listed order")
        elif spec and spec.operation_id == "pdf.organize_visual":
            parts.insert(0, "Save the reviewed thumbnail order as a new PDF")
        elif spec and spec.operation_id == "pdf.compare":
            parts.insert(0, "First PDF: original · Second PDF: revised")
        elif spec and spec.input_mode == "multiple":
            parts.insert(0, f"Combine {len(self._paths)} files in listed order")
        elif len(self._paths) > 1:
            parts.insert(0, f"Process {len(self._paths)} files separately")
        if not rename and self.output_name.text().strip():
            parts.append("Output: " + self.output_name.text().strip())
        self.summary.setText(" · ".join(parts))
        operation = spec.operation_id if spec else ""
        verb = (
            "Save copies"
            if operation == "file.rename_copies"
            else "Inspect details"
            if operation == "document.details"
            else "Compress"
            if "compress" in operation
            else "Clean metadata"
            if operation.startswith("metadata.clean")
            else "Inspect"
            if operation == "metadata.inspect"
            else "Redact"
            if operation == "pdf.redact"
            else "Convert"
            if ".to_" in operation
            else spec.label.split(" / ")[0]
            if spec
            else "Choose a tool"
        )
        self.start_button.setText(
            "Save organized copy" if operation == "pdf.organize_visual" else verb
        )
        if operation == "pdf.organize_visual" and self._page_organizer is not None:
            self.start_button.setEnabled(bool(self._page_organizer.value()) and not self._active)

    def _guard_run(self):
        self._preflight_errors = {}
        if not self._ux_ready:
            return True
        for path in self._paths:
            ready, reason = self._file_ready(path)
            if ready is None:
                self._requested_start = True
                self._stopping = False
                self._set_active(True)
                self._queue_inspection(path)
                self._set_result("ready", "Inspecting files", "Checking content before processing…")
                return False
            if not ready:
                self._preflight_errors[self._paths.index(path)] = reason
        if len(self._preflight_errors) == len(self._paths):
            self._retrying = False
            self._failed = set(self._preflight_errors)
            self._errors = dict(self._preflight_errors)
            self._rebuild_files()
            self._batch_finished_feedback()
            return False
        spec = self._current_spec()
        for label, found in self._engine_availability(spec.operation_id).items():
            if not found:
                self._retrying = False
                self._set_result(
                    "error",
                    f"{label} is needed",
                    "Open Tool availability to see which local engine is missing.",
                )
                return False
        if spec.operation_id == "pdf.organize_visual" and not self._page_organizer.value():
            self._set_result("error", "Review the page plan", self._page_organizer.error_message)
            return False
        organizer_idle = self._page_organizer is None or self._page_organizer.set_busy(True)
        if not self.document_preview.set_busy(True) or not organizer_idle:
            self._requested_start = True
            self._set_active(True)
            self._set_result("working", "Preparing", "Waiting for the preview worker…")
            return False
        return True

    @staticmethod
    def _engine_availability(operation=None):
        from local_pdf_toolkit.converters.media_metadata import find_ffmpeg
        from local_pdf_toolkit.converters.ocr import find_tesseract
        from local_pdf_toolkit.converters.office_pdf import find_libreoffice

        engines = {
            "LibreOffice": bool(find_libreoffice()),
            "Tesseract": bool(find_tesseract()),
            "FFmpeg / ffprobe": bool(find_ffmpeg()),
        }
        needed = {
            "office.to_pdf": "LibreOffice",
            "pdf.ocr": "Tesseract",
            "metadata.clean_media": "FFmpeg / ffprobe",
        }
        return (
            {needed[operation]: engines[needed[operation]]}
            if operation in needed
            else engines
            if operation is None
            else {}
        )

    def _show_recovery(self):
        from PySide6.QtWidgets import QMessageBox

        from local_pdf_toolkit.core.recovery import cleanup, list_recoverable

        try:
            records = list_recoverable()
        except OSError:
            QMessageBox.warning(self, "Interrupted jobs", "Could not read recovery records.")
            return
        if not records:
            QMessageBox.information(
                self, "Interrupted jobs", "No recoverable temporary files found."
            )
            return
        for record in records:
            message = (
                f"Interrupted job in {record.output_directory}\n"
                f"Temporary files: {record.file_count} · "
                f"{self._display_bytes(record.size_bytes)}\n\n"
                "Remove this job's temporary files? Saved outputs will be kept. "
                "An interrupted batch may have saved only some outputs."
            )
            if (
                QMessageBox.question(
                    self,
                    "Clean up interrupted job",
                    message,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                continue
            try:
                cleanup(record)
            except (OSError, RuntimeError, ValueError) as exc:
                QMessageBox.warning(self, "Cleanup could not finish", str(exc))

    def _show_availability(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Tool availability")
        layout = QVBoxLayout(dialog)
        status = QLabel()
        status.setWordWrap(True)

        def refresh():
            status.setText(
                "\n\n".join(
                    f"{name}: {'Available' if found else 'Not found — install locally'}"
                    for name, found in self._engine_availability().items()
                )
                + "\n\nLibreOffice: Office conversion and previews"
                "\nTesseract: searchable PDF OCR (language packs required)"
                "\nFFmpeg / ffprobe: audio and video cleanup"
                "\nNo engines are downloaded by the app."
            )

        layout.addWidget(status)
        check = QPushButton("Check again")
        check.clicked.connect(refresh)
        layout.addWidget(check)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        refresh()
        dialog.exec()
        dialog.deleteLater()

    def _paste_files(self):
        mime = QApplication.clipboard().mimeData()
        if mime and mime.hasUrls():
            self._suggest_tools = self.pages.currentWidget() == self.dashboard
            self.add_paths([url.toLocalFile() for url in mime.urls() if url.isLocalFile()])

    def _remap_edited_results(self, old_paths):
        results = {path: self._results[i] for i, path in enumerate(old_paths) if i in self._results}
        errors = {path: self._errors[i] for i, path in enumerate(old_paths) if i in self._errors}
        failed = {old_paths[i] for i in self._failed if i < len(old_paths)}
        self._results = {i: results[path] for i, path in enumerate(self._paths) if path in results}
        self._errors = {i: errors[path] for i, path in enumerate(self._paths) if path in errors}
        self._failed = {i for i, path in enumerate(self._paths) if path in failed}
        self._rebuild_files()
        if self._results or self._failed:
            self._batch_finished_feedback()
        else:
            self._set_result("ready", "Ready", "Add a file or choose your settings.")
            self._selection_changed()

    def _remember_file_change(self):
        self._undo.append(
            (list(self._paths), dict(self._results), set(self._failed), dict(self._errors))
        )
        del self._undo[:-20]

    def _undo_file_change(self):
        if self._active or not self._undo:
            return
        self._paths, self._results, self._failed, self._errors = self._undo.pop()
        self._rebuild_files()
        self._sync_files()
        self._selection_changed()

    def _open_selected_result(self):
        index = self.files.currentRow()
        paths = self._results.get(index, ())
        path = next((p for p in paths if p.suffix.lower() != ".json"), paths[0] if paths else None)
        if path and path.suffix.lower() == ".json":
            self._open_report()
        elif path:
            if not path.is_file() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self._set_result(
                    "error",
                    "Could not open result",
                    "Check that the result still exists, or open the output folder.",
                )

    def _adjust_settings(self):
        if getattr(self, "_error_action", "") == "folder":
            self._choose_directory()
            return
        self.settings_panel.setVisible(True)
        self.settings_action.setChecked(True)
        if getattr(self, "_error_action", "") == "rename":
            editor = (
                self._editors["base_name"].__self__
                if self._tool_id == "file.rename_copies"
                else self.output_name
            )
            section = (
                self.options_section
                if self._tool_id == "file.rename_copies"
                else self.output_section
            )
            section.open()
            section.scroll.ensureWidgetVisible(editor)
            editor.setFocus()
            editor.selectAll()
        else:
            self.options_section.open()
            self.options_widget.setFocus()

    def _file_menu(self, position):
        item = self.files.itemAt(position)
        if item is None:
            return
        self.files.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("Preview", self._open_preview)
        if self.files.currentRow() in self._results:
            menu.addAction("Open result", self._open_selected_result)
            menu.addAction("Compare", self._open_comparison)
        menu.addSeparator()
        menu.addAction("Remove from workspace", self._remove).setEnabled(not self._active)
        menu.exec(self.files.viewport().mapToGlobal(position))

    def _resource_idle(self):
        workers_idle = (
            not self.jobs.running
            and not self._probe_jobs.running
            and not self.document_preview.running
            and (self._page_organizer is None or not self._page_organizer.running)
        )
        if (self._closing or self._stopping) and workers_idle:
            self._set_active(False)
            if self._closing:
                QTimer.singleShot(0, self.close)
            else:
                self._pending.clear()
                self._batch_finished_feedback()
        elif (
            self._requested_start
            and not self._probe_jobs.running
            and not self.document_preview.running
            and (self._page_organizer is None or not self._page_organizer.running)
        ):
            QTimer.singleShot(0, self._resume_requested_start)

    def _resume_requested_start(self):
        if not self._requested_start or self._closing or self._stopping:
            return
        self._requested_start = False
        # Keep the workspace busy until the continuation actually runs. Exposing
        # an idle event-loop turn here permits duplicate actions and early exit.
        self._set_active(False)
        self._start()

    def _close_workspace(self):
        from local_pdf_toolkit.ui.controls import InfoButton

        for section in (self.options_section, self.advanced_section, self.output_section):
            section.close()
        for info in self.findChildren(InfoButton):
            if info._popover is not None:
                info._popover.hide()
        self._requested_start = False
        self._probe_queue.clear()
        if self._probe_jobs.running:
            self._probe_jobs.cancel()
        preview_done = self.document_preview.shutdown()
        organizer_done = self._page_organizer is None or self._page_organizer.shutdown()
        if self._probe_jobs.running or not preview_done or not organizer_done:
            return False
        self._probe_temp.cleanup()
        self._preferences.setValue("windowGeometry", self.saveGeometry())
        self._preferences.setValue("workspaceSizes", self.workspace_splitter.sizes())
        if self.sidebar.isVisible():
            self._preferences.setValue("librarySizes", self.library_splitter.sizes())
        if "target_unit" in self._editors:
            self._preferences.setValue("preferredUnit", self._editors["target_unit"]())
        return True
