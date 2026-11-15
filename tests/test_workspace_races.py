"""Regressions for cancellation and custom naming across workspace components."""

import pymupdf
import pytest
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtWidgets import QDialog
from test_workspace import choose, inspected, process
from test_workspace import workspace as workspace

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.main_window import MainWindow


class ControlledJobs(QObject):
    finished = Signal(object, object)
    progress = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.started = []
        self.cancelled = False

    def start(self, converter, source, output_dir, options):
        assert not self.running
        self.running = True
        self.started.append((converter, source, output_dir, options))

    def cancel(self):
        self.cancelled = True

    def complete(self, paths=(), error=None):
        self.running = False
        self.finished.emit(paths, error)


@pytest.fixture
def race_workspace(qapp, monkeypatch, tmp_path, fixture_dir):
    import local_pdf_toolkit.ui.document_preview as preview
    import local_pdf_toolkit.ui.main_window as main
    import local_pdf_toolkit.ui.workspace as behavior

    monkeypatch.setattr(preview, "JobController", ControlledJobs)
    monkeypatch.setattr(main, "JobController", ControlledJobs)
    monkeypatch.setattr(behavior, "JobController", ControlledJobs)
    monkeypatch.setattr(
        behavior,
        "QSettings",
        lambda *_: QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat),
    )
    window = MainWindow(build_registry())
    choose(window, "pdf.to_png")
    window.show()
    for name in ("first.pdf", "second.pdf"):
        source = tmp_path / name
        source.write_bytes((fixture_dir / "one_page.pdf").read_bytes())
        window._paths.append(source)
        window._records[source] = {
            "ready": True,
            "format": "pdf",
            "bytes": source.stat().st_size,
            "pages": 1,
            "signature": window._signature(source),
        }
    window._rebuild_files()
    window._sync_files()
    window.files.setCurrentRow(0)
    window._selection_changed()
    window.document_preview._debounce.stop()
    window.destination.setText(str(tmp_path))
    qapp.processEvents()
    yield window
    # Controlled workers own no processes; recover even after a regression assertion.
    window._requested_start = False
    window._active = False
    window.jobs.running = False
    window._probe_jobs.running = False
    window.document_preview.jobs.running = False
    window._pending.clear()
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("action", ("cancel", "close"))
def test_cancel_or_close_while_start_waits_for_preview_exit(race_workspace, qapp, action):
    window = race_workspace
    window.document_preview._render()
    assert window.document_preview.running
    window._start()
    assert window._active and window._requested_start and not window.jobs.running
    if action == "close":
        window.close()
    else:
        window._cancel()
    window.document_preview.jobs.complete(error=("cancelled", "Cancelled"))
    qapp.processEvents()
    assert not window._active
    assert not window._requested_start
    if action == "close":
        assert not window.isVisible()
    else:
        assert window.start_button.isEnabled()


def test_bulk_name_normalizes_typed_extension_before_adding_index(race_workspace):
    window = race_workspace
    window.output_name.setText("Invoice.PNG")
    window._start()
    assert window.jobs.running
    converter = window.jobs.started[0][0]
    assert converter.base_name == "Invoice-1"


def test_named_inspection_json_can_be_opened_as_report(race_workspace, tmp_path, monkeypatch):
    window = race_workspace
    report = tmp_path / "Chosen.json"
    report.write_text('{"inspection": [], "policy": "Synthetic report"}')
    window._results[0] = (report,)
    shown = []
    monkeypatch.setattr(QDialog, "exec", lambda dialog: shown.append(dialog.windowTitle()) or 0)
    window._open_selected_result()
    assert shown, "View report must accept the actual named JSON output."


def test_cancel_selected_queued_conversion_records_cancellation(race_workspace):
    window = race_workspace
    window._start()
    assert window.jobs.running and [index for index, _ in window._pending] == [1]
    window.files.setCurrentRow(1)
    window._cancel_one()
    assert not window._pending
    assert window._cancelled == {1}
    assert 1 in window._failed


def test_cancelled_inspection_can_be_requested_again(race_workspace):
    window = race_workspace
    source = window._paths[0]
    window._records.pop(source)
    window._queue_inspection(source)
    assert window._probe_jobs.running
    window._start()
    assert window._requested_start and window._active
    window._cancel()
    window._probe_jobs.complete(error=("cancelled", "Cancelled"))
    assert source not in window._records
    assert window._file_ready(source)[0] is None
    assert not window._active
    window._start()
    assert window._probe_jobs.running
    assert len(window._probe_jobs.started) == 2


def test_encrypted_pdf_can_be_unlocked_after_content_inspection(workspace, tmp_path):  # noqa: F811
    choose(workspace, "pdf.unlock")
    source = tmp_path / "protected.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(
            source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
    original = source.read_bytes()
    workspace.add_paths((source,))
    inspected(workspace)
    record = workspace._records[source]
    assert record["format"] == "pdf" and record["error_code"] == "password_required"
    workspace._editors["password"].__self__.setText("secret")
    process(workspace, tmp_path)
    assert workspace.result_banner.property("state") == "success"
    assert set(workspace._results) == {0}
    (output,) = workspace._results[0]
    with pymupdf.open(output) as document:
        assert document.is_pdf and not document.needs_pass
    assert source.read_bytes() == original


def test_rejected_retry_does_not_contaminate_next_tool(race_workspace, tmp_path):
    window = race_workspace
    for source in window._paths:
        window._records[source]["ready"] = False
        window._records[source]["reason"] = "Invalid PDF"
    window._failed = {0, 1}
    window._retry()
    assert not window._retrying
    choose(window, "image.to_png")
    assert not window._retrying
    assert not window._paths
    from PIL import Image

    source = tmp_path / "valid.png"
    Image.new("RGB", (10, 10), "red").save(source)
    window._paths = [source]
    window._records[source] = {
        "ready": True,
        "format": "png",
        "bytes": source.stat().st_size,
        "signature": window._signature(source),
    }
    window._rebuild_files()
    window._start()
    assert window.jobs.started
