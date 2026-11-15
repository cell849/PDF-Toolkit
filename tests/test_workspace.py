"""User-visible workspace flows with real asynchronous inspection and conversion."""

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QSettings, Qt, QTimer
from PySide6.QtTest import QTest

from local_pdf_toolkit.app import build_registry
from local_pdf_toolkit.ui.controls import SliderNumber, TargetSizeEditor
from local_pdf_toolkit.ui.main_window import MainWindow


def wait_until(predicate, description, timeout_ms=15000):
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout.timeout.connect(loop.quit)
    poll.start(20)
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    assert predicate(), f"Timed out waiting for {description}"


@pytest.fixture
def workspace(qapp, monkeypatch, tmp_path):
    import local_pdf_toolkit.ui.workspace as behavior

    monkeypatch.setattr(
        behavior,
        "QSettings",
        lambda *_: QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat),
    )
    window = MainWindow(build_registry())
    window.resize(1380, 860)
    window.show()
    yield window
    window.close()
    wait_until(
        lambda: not window.isVisible()
        and not window.jobs.running
        and not window._probe_jobs.running
        and not window.document_preview.jobs.running,
        "workspace and all workers to close",
    )
    window.deleteLater()
    qapp.processEvents()


def choose(window, operation):
    window._select_tool(
        next(i for i, spec in enumerate(window._operations) if spec.operation_id == operation)
    )


def inspected(window):
    wait_until(
        lambda: not window._probe_jobs.running
        and not window._probe_queue
        and all(path in window._records for path in window._paths),
        "metadata inspection",
    )


def process(window, destination):
    window.destination.setText(str(destination))
    window._start()
    wait_until(
        lambda: not window._active
        and not window._requested_start
        and not window._probe_jobs.running
        and not window._probe_queue
        and not window.jobs.running
        and window.result_banner.property("state") in {"success", "partial", "error", "cancelled"},
        "persistent processing result",
    )


def copies(fixture_dir, tmp_path, names=("one", "two")):
    result = []
    for name in names:
        path = tmp_path / f"{name}.pdf"
        path.write_bytes((fixture_dir / "one_page.pdf").read_bytes())
        result.append(path)
    return result


def test_invalid_preflight_shows_failure_without_finished_success(workspace, tmp_path):
    choose(workspace, "pdf.to_png")
    invalid = tmp_path / "broken.pdf"
    invalid.write_bytes(b"%PDF-1.7\nthis is not a document")
    workspace.add_paths((invalid,))
    inspected(workspace)
    assert workspace._file_ready(invalid)[0] is False
    process(workspace, tmp_path)
    assert workspace._failed == {0}
    assert not workspace._results
    assert workspace.result_banner.property("state") == "error"
    assert "failed" in workspace.result_title.text().lower()
    assert workspace.result_detail.text().strip()
    assert workspace.files.item(0).text().startswith("Failed")
    assert "Finished" not in workspace.feedback.text()
    assert workspace.result_retry.isVisible()


def test_mixed_batch_keeps_valid_outputs_and_reports_invalid_file(
    workspace,
    fixture_dir,
    tmp_path,
):
    choose(workspace, "pdf.to_png")
    invalid = tmp_path / "broken.pdf"
    invalid.write_bytes(b"broken PDF")
    (valid,) = copies(fixture_dir, tmp_path, ("valid",))
    workspace.add_paths((invalid, valid))
    process(workspace, tmp_path)
    assert workspace._failed == {0}
    assert set(workspace._results) == {1}
    outputs = workspace._results[1]
    assert outputs and all(path.is_file() for path in outputs)
    assert workspace.result_banner.property("state") == "partial"
    assert workspace.result_title.text() == "1 saved · 1 failed"
    assert workspace.result_detail.text().strip()
    assert workspace.files.item(1).text().startswith("Done")
    workspace.files.setCurrentRow(1)
    assert workspace.result_compare.isVisible() and workspace.result_compare.isEnabled()
    workspace.files.setCurrentRow(0)
    assert not workspace.result_compare.isVisible()


def test_incompatible_tool_switch_hides_pdf_and_return_restores_results(
    workspace,
    fixture_dir,
    tmp_path,
):
    choose(workspace, "pdf.to_png")
    (source,) = copies(fixture_dir, tmp_path, ("source",))
    workspace.add_paths((source,))
    process(workspace, tmp_path)
    saved = dict(workspace._results)
    choose(workspace, "image.to_jpeg")
    assert not workspace._paths
    assert workspace.files.count() == 0
    assert not workspace._results
    choose(workspace, "pdf.to_png")
    assert workspace._paths == [source]
    assert workspace._results == saved
    assert all(path.is_file() for paths in saved.values() for path in paths)


def test_compatible_tool_switch_keeps_inspected_file(workspace, fixture_dir, tmp_path):
    choose(workspace, "pdf.to_png")
    (source,) = copies(fixture_dir, tmp_path, ("source",))
    workspace.add_paths((source,))
    inspected(workspace)
    choose(workspace, "pdf.compress")
    assert workspace._paths == [source]
    assert workspace._file_ready(source) == (True, "Ready")
    assert workspace.files.count() == 1
    assert not workspace._results


@pytest.mark.parametrize("change", ("remove", "reorder"))
def test_undo_file_change_restores_order_and_completed_results(
    workspace,
    fixture_dir,
    tmp_path,
    change,
):
    choose(workspace, "pdf.to_png")
    sources = copies(fixture_dir, tmp_path)
    workspace.add_paths(sources)
    process(workspace, tmp_path)
    saved = dict(workspace._results)
    workspace.files.setCurrentRow(1)
    if change == "remove":
        workspace._remove()
        assert workspace._paths == sources[:1]
    else:
        workspace._move(-1)
        assert workspace._paths == list(reversed(sources))
    workspace._undo_file_change()
    assert workspace._paths == sources
    assert workspace._results == saved
    assert all(workspace.files.item(i).text().startswith("Done") for i in (0, 1))
    assert all(path.is_file() for paths in saved.values() for path in paths)


def test_cancel_selected_while_preflight_queued_preserves_other_jobs(
    workspace,
    fixture_dir,
    tmp_path,
):
    choose(workspace, "pdf.to_png")
    sources = copies(fixture_dir, tmp_path, ("first", "cancelled", "last"))
    workspace.add_paths(sources)
    workspace.destination.setText(str(tmp_path))
    workspace._start()
    assert workspace._requested_start and workspace._active
    workspace.files.setCurrentRow(1)
    workspace._cancel_one()
    wait_until(
        lambda: not workspace._active
        and not workspace._requested_start
        and not workspace.jobs.running
        and not workspace._probe_jobs.running
        and workspace.result_banner.property("state") == "cancelled",
        "remaining jobs after queued preflight cancellation",
    )
    assert set(workspace._results) == {0, 2}
    assert workspace._cancelled == {1}
    assert not (tmp_path / "cancelled_page-0001.png").exists()
    assert all(path.is_file() for paths in workspace._results.values() for path in paths)
    assert workspace.result_title.text() == "Cancelled"


def test_close_during_queued_preflight_cleans_workers_and_temporary_folders(
    workspace,
    fixture_dir,
    tmp_path,
):
    choose(workspace, "pdf.to_png")
    workspace.add_paths(copies(fixture_dir, tmp_path, ("first", "second", "third")))
    probe_folder = Path(workspace._probe_temp.name)
    preview_folder = Path(workspace.document_preview._temp.name)
    workspace.destination.setText(str(tmp_path))
    workspace._start()
    assert workspace._requested_start and workspace._probe_jobs.running
    workspace.close()
    wait_until(
        lambda: not workspace.isVisible()
        and not workspace._probe_jobs.running
        and not workspace.jobs.running
        and not workspace.document_preview.jobs.running
        and not probe_folder.exists()
        and not preview_folder.exists(),
        "preflight cancellation and temporary folder cleanup",
    )
    assert not workspace._requested_start
    assert not workspace._probe_queue
    assert not workspace._results
    assert not list(tmp_path.glob("*_page-*.png"))


def test_fractional_percent_summary_keeps_exact_values_and_marks_previous_run_stale(
    workspace,
    tmp_path,
):
    choose(workspace, "image.to_jpeg")
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 80), "blue").save(source)
    workspace.add_paths((source,))
    process(workspace, tmp_path)
    saved = dict(workspace._results)
    target = workspace.findChild(TargetSizeEditor)
    target.unit.setCurrentIndex(target.unit.findData("percent"))
    target.amount.setValue(12.5)
    quality = workspace._editors["quality"].__self__
    assert isinstance(quality, SliderNumber)
    quality.number.setFocus()
    quality.number.selectAll()
    QTest.keyClicks(quality.number, "83")
    QTest.keyClick(quality.number, Qt.Key.Key_Return)
    assert workspace._editors["target_value"]() == 12.5
    assert workspace._editors["target_unit"]() == "percent"
    assert workspace._editors["quality"]() == 83
    assert "Keep 12.5% of original bytes" in workspace.summary.text()
    assert (
        f"Target total ≤ {int(source.stat().st_size * 0.125):,} bytes" in workspace.summary.text()
    )
    assert "Quality 83" in workspace.summary.text()
    assert workspace._results == saved
    assert workspace.document_preview.stale_label.isVisible()
    assert workspace.document_preview.stale_label.text() == "Previous run — settings changed"


def test_preview_action_stays_discoverable_empty_loaded_and_compact(
    workspace,
    fixture_dir,
    tmp_path,
    qapp,
):
    choose(workspace, "pdf.to_png")
    assert workspace.preview_button.isVisible()
    assert not workspace.preview_button.isEnabled()
    workspace.add_paths(copies(fixture_dir, tmp_path, ("source",)))
    inspected(workspace)
    assert workspace.preview_button.isVisible() and workspace.preview_button.isEnabled()
    workspace.resize(760, 620)
    qapp.processEvents()
    button = workspace.preview_button
    center = button.mapTo(workspace.files_scroll.viewport(), button.rect().center())
    assert workspace.files_scroll.viewport().rect().contains(center)
    workspace._clear()
    assert button.isVisible() and not button.isEnabled()


def test_dashboard_drop_suggests_compatible_tools_without_processing(workspace, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    window = workspace
    source = tmp_path / "picture.png"
    Image.new("RGB", (24, 30), "blue").save(source)
    original = source.read_bytes()
    window._show_library()
    window.search.setText("Compress PDF")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(
        QPointF(100, 100),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)
    wait_until(
        lambda: source in window._records and not window._probe_jobs.running,
        "dashboard file inspection",
    )
    assert window.pages.currentWidget() == window.dashboard
    visible = [
        spec
        for index, spec in enumerate(window._operations)
        if not window.operation_list.item(index).isHidden()
    ]
    assert visible and all(
        any(kind.value == "png" for kind in spec.input_formats) for spec in visible
    )
    assert not window.jobs.running and not window._results
    assert source.read_bytes() == original


def test_file_icons_do_not_retain_full_resolution_preview_rasters(workspace, tmp_path):
    from PySide6.QtGui import QPixmap

    source = tmp_path / "large-preview.png"
    Image.new("RGB", (20, 20), "blue").save(source)
    choose(workspace, "image.to_png")
    workspace.add_paths([source])
    inspected(workspace)
    pixmap = QPixmap(1400, 1000)
    pixmap.fill(Qt.GlobalColor.red)
    workspace._thumbnail_ready(pixmap)
    sizes = workspace.files.currentItem().icon().availableSizes()
    assert sizes and all(size.width() <= 64 and size.height() <= 64 for size in sizes)
