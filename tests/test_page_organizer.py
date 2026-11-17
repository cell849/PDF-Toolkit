"""Page identity, byte binding, resource limits, and accessible arrangement regressions."""

import hashlib
import json
import os
import time
from pathlib import Path

import pymupdf
import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent

from local_pdf_toolkit.converters import page_organizer as module
from local_pdf_toolkit.converters.page_organizer import (
    OrganizerPreviewConverter,
    PdfPageOrganizerConverter,
    canonical_plan,
    parse_plan,
)
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.ui.page_organizer import CACHE_ITEMS, PageOrganizerControl


@pytest.fixture
def pdfs(tmp_path):
    paths = []
    for name, count in (("first", 3), ("insert", 2)):
        path = tmp_path / f"{name}.pdf"
        with pymupdf.open() as document:
            for index in range(count):
                page = document.new_page(width=240 + index * 20, height=320)
                page.draw_rect(pymupdf.Rect(10, 10, 35, 35), color=(1, 0, 0), fill=(1, 0, 0))
                page.insert_text((20, 70), f"{name} page {index + 1}")
            document.set_metadata({"author": "ORIGINALCANARY"})
            document.save(path)
        paths.append(path)
    return tuple(paths)


def plan_for(paths):
    sources = []
    pages = []
    for path in paths:
        stat = path.stat()
        with pymupdf.open(path) as source:
            count = len(source)
        sources.append(
            {
                "path": str(path.resolve()),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "pages": count,
            }
        )
        pages.extend(
            {"path": str(path.resolve()), "page": index, "rotation": 0}
            for index in range(1, count + 1)
        )
    return {"version": 1, "sources": sources, "pages": pages}


def save(paths, output, plan, progress=lambda _: None, token=None):
    return PdfPageOrganizerConverter().convert(
        paths, output, {"plan": canonical_plan(plan)}, progress, token or CancellationToken()
    )


def test_vector_content_order_rotation_insert_and_originals(pdfs, tmp_path):
    before = [path.read_bytes() for path in pdfs]
    plan = plan_for(pdfs)
    plan["pages"] = [plan["pages"][2], plan["pages"][3], plan["pages"][0]]
    plan["pages"][1]["rotation"] = 90
    updates = []
    (output,) = save(pdfs, tmp_path, plan, updates.append)
    assert output.name == "first_organized.pdf"
    with pymupdf.open(output) as result:
        assert [page.get_text().strip() for page in result] == [
            "first page 3",
            "insert page 1",
            "first page 1",
        ]
        assert result[1].rotation == 90
        assert all(page.get_drawings() for page in result)
        for index, entry in enumerate(plan["pages"]):
            with pymupdf.open(entry["path"]) as source:
                page = source[entry["page"] - 1]
                page.set_rotation((page.rotation + entry["rotation"]) % 360)
                assert result[index].get_pixmap().samples == page.get_pixmap().samples
    assert [path.read_bytes() for path in pdfs] == before
    assert (updates[-1].completed, updates[-1].total) == (3, 3)
    with pytest.raises(ConversionError) as error:
        save(pdfs, tmp_path, plan)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert [path.read_bytes() for path in pdfs] == before


def test_feature_limit_form_appearance_baked_links_removed(pdfs, tmp_path):
    path = pdfs[0]
    with pymupdf.open(path) as source:
        widget = pymupdf.Widget()
        widget.field_name = "field"
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.field_value = "Form appearance"
        widget.rect = pymupdf.Rect(20, 100, 220, 130)
        source[0].add_widget(widget)
        source[0].insert_link(
            {
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(10, 10, 20, 20),
                "uri": "https://example.invalid",
            }
        )
        source.saveIncr()
    (output,) = save((path,), tmp_path, plan_for((path,)))
    with pymupdf.open(output) as result:
        assert not result[0].get_links()
        assert not list(result[0].widgets())
        assert "Form appearance" in result[0].get_text()


def test_same_signature_changed_bytes_rejected_before_parser(pdfs, tmp_path, monkeypatch):
    plan = plan_for(pdfs)
    path = pdfs[0]
    previous = path.stat()
    content = path.read_bytes().replace(b"ORIGINALCANARY", b"MODIFIEDCANARY")
    path.write_bytes(content)
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert path.stat().st_size == previous.st_size
    monkeypatch.setattr(module, "_open", lambda *_: pytest.fail("Stale source parsed"))
    with pytest.raises(ConversionError) as error:
        save(pdfs, tmp_path, plan)
    assert error.value.code == ErrorCode.INVALID_INPUT
    assert not list(tmp_path.glob("*organized*"))
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_snapshot_used_when_original_changes_after_copy(pdfs, tmp_path, monkeypatch):
    plan = plan_for(pdfs)
    original_snapshot = module._snapshot

    def snapshot(path, *args, **kwargs):
        info = original_snapshot(path, *args, **kwargs)
        path.write_bytes(b"source replaced after verified snapshot")
        return info

    monkeypatch.setattr(module, "_snapshot", snapshot)
    (output,) = save(pdfs, tmp_path, plan)
    with pymupdf.open(output) as result:
        assert len(result) == 5
        assert "first page 1" in result[0].get_text()


@pytest.mark.parametrize(
    "change",
    [
        lambda plan: plan["pages"].clear(),
        lambda plan: plan["pages"][0].update(page=True),
        lambda plan: plan["pages"][0].update(page=99),
        lambda plan: plan["pages"][0].update(rotation=45),
        lambda plan: plan["pages"][0].update(path="/unselected.pdf"),
        lambda plan: plan["sources"][0].update(sha256="g" * 64),
        lambda plan: plan["sources"][0].update(pages=True),
        lambda plan: plan["sources"][0].update(path="../relative.pdf"),
        lambda plan: plan.update(version=True),
        lambda plan: plan.update(unexpected=1),
    ],
)
def test_invalid_plans_fail_closed(pdfs, change):
    plan = plan_for(pdfs)
    change(plan)
    with pytest.raises(ConversionError) as error:
        parse_plan(canonical_plan(plan))
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_selected_sources_are_authority_not_plan_paths(pdfs, tmp_path, monkeypatch):
    plan = plan_for(pdfs)
    monkeypatch.setattr(module, "_snapshot", lambda *_: pytest.fail("Unapproved path accessed"))
    with pytest.raises(ConversionError) as error:
        save((pdfs[0],), tmp_path, plan)
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_cancellation_rolls_back_before_publication(pdfs, tmp_path):
    token = CancellationToken()

    def progress(value):
        if value.completed == 1:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        save(pdfs, tmp_path, plan_for(pdfs), progress, token)
    assert sorted(tmp_path.glob("*.pdf")) == sorted(pdfs)
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_scan_content_validation_and_bounded_thumbnail(pdfs, tmp_path):
    directory = tmp_path / "previews"
    directory.mkdir()
    converter = OrganizerPreviewConverter()
    outputs = converter.convert(
        pdfs, directory, {"mode": "scan"}, lambda _: None, CancellationToken()
    )
    manifest = json.loads(outputs[0].read_text())
    source = manifest["sources"][0]
    assert source == plan_for(pdfs)["sources"][0]
    (image,) = converter.convert(
        directory / manifest["prepared"][str(pdfs[0])],
        directory,
        {"page": 1, "rotation": 90},
        lambda _: None,
        CancellationToken(),
    )
    from PIL import Image

    with Image.open(image) as thumbnail:
        assert max(thumbnail.size) <= module.THUMBNAIL_EDGE + 1
        assert thumbnail.width > thumbnail.height
    invalid = tmp_path / "fake.pdf"
    invalid.write_bytes(b"this is not a PDF")
    with pytest.raises(ConversionError):
        converter.convert(
            (invalid,), directory, {"mode": "scan"}, lambda _: None, CancellationToken()
        )
    assert not list(directory.glob(".pdf-toolkit-*"))


def test_resource_and_json_bounds(pdfs, monkeypatch):
    plan = plan_for(pdfs)
    monkeypatch.setattr(module, "MAX_PLAN_BYTES", 20)
    with pytest.raises(ConversionError):
        parse_plan(canonical_plan(plan))
    monkeypatch.setattr(module, "MAX_PLAN_BYTES", 8 * 1024 * 1024)
    monkeypatch.setattr(module, "MAX_INPUT_BYTES", 1)
    with pytest.raises(ConversionError):
        parse_plan(canonical_plan(plan))


def wait_for(qapp, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("Organizer worker did not finish")


def close_control(qapp, control):
    if not control.shutdown():
        wait_for(qapp, lambda: not control.running)
    control.deleteLater()
    qapp.processEvents()


def test_grid_keyboard_multi_selection_delete_rotate_undo(qapp, pdfs):
    control = PageOrganizerControl()
    control._paths = pdfs
    plan = plan_for(pdfs)
    control._sources, control._pages = plan["sources"], plan["pages"]
    control.error_message = ""
    control.set_busy(True)  # This test exercises editing without a thumbnail process.
    control._busy = False
    control._rebuild()
    control._timer.stop()
    try:
        control.grid.item(0).setSelected(True)
        control.grid.item(2).setSelected(True)
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier
        )
        control.grid.keyPressEvent(event)
        assert [page["page"] for page in control._pages] == [2, 1, 1, 3, 2]
        assert control.selected_rows() == [2, 3]
        control.rotate_selected()
        assert [page["rotation"] for page in control._pages] == [0, 0, 90, 90, 0]
        control.delete_selected()
        assert len(json.loads(control.value())["pages"]) == 3
        control.undo()
        assert len(control._pages) == 5
        control.grid.selectAll()
        control.delete_selected()
        assert len(control._pages) == 5
    finally:
        close_control(qapp, control)


def test_worker_scan_insert_preserves_arrangement_and_cache_bound(qapp, pdfs):
    control = PageOrganizerControl()
    control.resize(760, 520)
    control.show()
    try:
        control.set_sources((pdfs[0],))
        assert control.value() == ""
        wait_for(qapp, lambda: bool(control.value()))
        control.grid.item(2).setSelected(True)
        control.move_selected_to(0)
        assert control._pages[0]["page"] == 3
        control.grid.clearSelection()
        control.grid.item(0).setSelected(True)
        control.insert_files((pdfs[1],))
        wait_for(qapp, lambda: bool(control.value()) and len(control._pages) == 5)
        plan = json.loads(control.value())
        assert [(Path(page["path"]).name, page["page"]) for page in plan["pages"]] == [
            ("first.pdf", 3),
            ("insert.pdf", 1),
            ("insert.pdf", 2),
            ("first.pdf", 1),
            ("first.pdf", 2),
        ]
        wait_for(qapp, lambda: len(control._cache) >= 1)
        assert len(control._cache) <= CACHE_ITEMS
        assert control.grid.item(0).data(Qt.ItemDataRole.AccessibleTextRole)
    finally:
        close_control(qapp, control)


def test_input_acceptance_uses_content_and_rejects_encryption(pdfs, tmp_path):
    renamed = tmp_path / "actual-pdf.bin"
    renamed.write_bytes(pdfs[0].read_bytes())
    converter = PdfPageOrganizerConverter()
    assert converter.validate_input((renamed,)).value == "pdf"
    locked = tmp_path / "locked.pdf"
    with pymupdf.open(pdfs[0]) as source:
        source.save(
            locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner-only", user_pw=""
        )
    with pytest.raises(ConversionError) as error:
        converter.validate_input((locked,))
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED


def test_snapshot_cancellation_checked_between_bounded_reads(pdfs, tmp_path):
    class CancelAfterChunk(CancellationToken):
        checks = 0

        def raise_if_cancelled(self):
            self.checks += 1
            if self.checks == 2:
                self.cancel()
            super().raise_if_cancelled()

    token = CancelAfterChunk()
    with pytest.raises(ConversionCancelled):
        module._snapshot(pdfs[0], tmp_path / "partial.pdf", token)
    assert token.checks == 2
    assert (tmp_path / "partial.pdf").stat().st_size <= 1024 * 1024


def test_grid_drop_reorders_group_and_keeps_selection(qapp, pdfs):
    control = PageOrganizerControl()
    plan = plan_for(pdfs)
    control._sources, control._pages = plan["sources"], plan["pages"]
    control.error_message = ""
    control._rebuild()
    control._timer.stop()
    control.resize(700, 500)
    control.show()
    qapp.processEvents()
    control._timer.stop()
    try:
        control.grid.item(0).setSelected(True)
        control.grid.item(2).setSelected(True)
        rect = control.grid.visualItemRect(control.grid.item(4))

        class Drop:
            accepted = False
            action = None

            def source(self):
                return control.grid

            def position(self):
                return QPointF(rect.right() - 1, rect.center().y())

            def setDropAction(self, action):
                self.action = action

            def accept(self):
                self.accepted = True

        event = Drop()
        control.grid.dropEvent(event)
        assert event.accepted
        assert event.action == Qt.DropAction.MoveAction
        assert control.selected_rows() == [3, 4]
        assert [page["page"] for page in control._pages] == [2, 1, 2, 1, 3]
    finally:
        close_control(qapp, control)


def test_pause_scan_cancellation_resumes_instead_of_losing_plan(qapp, pdfs):
    control = PageOrganizerControl()
    try:
        control.set_sources(pdfs)
        control._timer.stop()
        control._active = (control._generation, "scan", None)
        control.set_busy(True)
        control._finished((), ("cancelled", "Conversion cancelled."))
        assert control._pending_scan
        assert not control.value()
        control.set_busy(False)
        wait_for(qapp, lambda: bool(control.value()))
        assert len(json.loads(control.value())["pages"]) == 5
    finally:
        close_control(qapp, control)
