"""User-visible naming plans and reports across real worker boundaries."""

import json
from pathlib import Path

import pymupdf
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPlainTextEdit
from test_workspace import choose, inspected, process, wait_until
from test_workspace import workspace as _shared_workspace

workspace = _shared_workspace


def test_live_names_follow_options_and_order_then_match_saved_copies(
    workspace, fixture_dir, tmp_path, qapp, monkeypatch
):
    choose(workspace, "file.rename_copies")
    sources = [tmp_path / "First.pdf", tmp_path / "Second.pdf"]
    for path in sources:
        path.write_bytes((fixture_dir / "one_page.pdf").read_bytes())
    workspace.add_paths(sources)
    inspected(workspace)
    assert not workspace.output_name.isEnabled()
    prefix = workspace._editors["prefix"].__self__
    QTest.keyClicks(prefix, "Copy ")
    workspace.files.setCurrentRow(1)
    workspace._move(-1)
    table = workspace._rename_preview.table
    planned = [table.item(row, 1).text() for row in range(table.rowCount())]
    assert planned == ["Copy Second-001.pdf", "Copy First-002.pdf"]
    assert not workspace.document_preview.running
    workspace.output_name.setText("Ignored")  # A disabled generic name cannot replace the plan.
    destination = tmp_path / "copies"
    destination.mkdir()
    process(workspace, destination)
    assert not workspace._failed
    assert sorted(path.name for path in destination.iterdir()) == sorted(planned)
    for source, name in zip(reversed(sources), planned, strict=True):
        assert (destination / name).read_bytes() == source.read_bytes()
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True
    )
    workspace.files.setCurrentRow(1)
    workspace._open_selected_result()
    assert len(opened) == 1 and Path(opened[0]) == destination / "Copy First-002.pdf"
    process(workspace, destination)
    assert workspace._failed and "already exists" in workspace.result_detail.text()
    workspace.result_adjust.click()
    assert qapp.focusWidget() is workspace._editors["base_name"].__self__
    assert sorted(path.name for path in destination.iterdir()) == sorted(planned)


def test_retry_of_group_preflight_failure_keeps_entire_numbered_plan(
    workspace, fixture_dir, tmp_path
):
    choose(workspace, "file.rename_copies")
    first, second = tmp_path / "First.pdf", tmp_path / "Second.pdf"
    original = (fixture_dir / "one_page.pdf").read_bytes()
    first.write_bytes(original)
    second.write_bytes(b"broken")
    workspace.add_paths((first, second))
    destination = tmp_path / "copies"
    destination.mkdir()
    process(workspace, destination)
    assert workspace._failed and not list(destination.iterdir())
    second.write_bytes(original)
    workspace._retry()
    wait_until(lambda: not workspace._active and not workspace._requested_start, "retry")
    assert not workspace._failed
    assert sorted(path.name for path in destination.iterdir()) == [
        "First-001.pdf",
        "Second-002.pdf",
    ]


def test_locked_document_details_are_readable_in_report_without_password(
    workspace, tmp_path, monkeypatch
):
    source = tmp_path / "locked.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.save(
            source, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret"
        )
    choose(workspace, "document.details")
    workspace.add_paths((source,))
    process(workspace, tmp_path)
    assert not workspace._failed
    (path,) = workspace._results[0]
    assert json.loads(path.read_text())["document_details"]["password_required"]
    displayed = []
    monkeypatch.setattr(
        QDialog,
        "exec",
        lambda dialog: displayed.append(dialog.findChild(QPlainTextEdit).toPlainText()) or 0,
    )
    workspace._open_selected_result()
    assert "DOCUMENT DETAILS" in displayed[0]
    assert "Password required: Yes" in displayed[0]
    assert "CLEANING POLICY" not in displayed[0]


def test_unchanged_name_plan_preserves_table_selection(qapp):
    from local_pdf_toolkit.ui.rename_preview import RenamePreview

    preview = RenamePreview()
    try:
        paths = [Path(f"file-{index}.pdf") for index in range(1000)]
        preview.update_plan(paths, {})
        preview.table.selectRow(700)
        preview.update_plan(paths, {})
        assert preview.table.currentRow() == 700
        assert preview.table.item(700, 1).text() == "file-700-701.pdf"
    finally:
        preview.close()
