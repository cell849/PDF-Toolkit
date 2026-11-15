"""Independent behavioral models: no expected values from converter helpers."""

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from local_pdf_toolkit.converters.pdf_images import page_selection
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError
from local_pdf_toolkit.core.output import OutputTransaction


@settings(max_examples=150, deadline=None)
@given(st.integers(1, 100), st.lists(st.integers(1, 100), min_size=1, max_size=40))
def test_page_selection_matches_document_order(count, requested):
    expression = ",".join(str(page) for page in requested)
    if any(page > count for page in requested):
        with pytest.raises(ConversionError):
            page_selection(expression, count)
    else:
        expected = tuple(index for index in range(count) if index + 1 in requested)
        assert page_selection(expression, count) == expected


@settings(max_examples=100, deadline=None)
@given(st.integers(1, 100), st.integers(1, 100))
def test_ranges_have_inclusive_bounds(first, last):
    if first > last:
        with pytest.raises(ConversionError):
            page_selection(f"{first}-{last}", 100)
    else:
        assert page_selection(f"{first}-{last}", 100) == tuple(range(first - 1, last))


@settings(max_examples=100, deadline=None)
@given(st.lists(st.binary(max_size=64), min_size=1, max_size=6), st.integers(0, 6))
def test_publication_collision_rolls_back_only_own_files(payloads, collision):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        existing = root / f"file-{collision}"
        existing.write_bytes(b"keep-existing")
        unrelated = root / "unrelated"
        unrelated.write_bytes(b"keep-unrelated")
        names = [f"file-{index}" for index in range(len(payloads))]
        try:
            with OutputTransaction(root) as output:
                for name, payload in zip(names, payloads, strict=True):
                    (output.staging / name).write_bytes(payload)
                output.publish(names, CancellationToken())
        except FileExistsError:
            assert collision < len(names)
            assert {p.name for p in root.iterdir()} == {existing.name, unrelated.name}
        else:
            assert collision >= len(names)
            for name, payload in zip(names, payloads, strict=True):
                assert (root / name).read_bytes() == payload
        assert existing.read_bytes() == b"keep-existing"
        assert unrelated.read_bytes() == b"keep-unrelated"
        assert not list(root.glob(".pdf-toolkit-*"))


class CancelAfter:
    def __init__(self, checks):
        self.checks = checks

    def raise_if_cancelled(self):
        if self.checks == 0:
            raise ConversionCancelled()
        self.checks -= 1


@settings(max_examples=70, deadline=None)
@given(st.integers(1, 6), st.integers(0, 6))
def test_cancel_at_each_publication_boundary_is_atomic(count, checks):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        names = [f"part-{index}" for index in range(count)]
        try:
            with OutputTransaction(root) as output:
                for name in names:
                    (output.staging / name).write_bytes(b"result")
                output.publish(names, CancelAfter(checks))
        except ConversionCancelled:
            assert checks <= count
            assert not list(root.iterdir())
        else:
            assert checks > count
            assert sorted(p.name for p in root.iterdir()) == sorted(names)


@pytest.mark.parametrize("name", ["../escape", "sub/file", ".", ".."])
def test_output_names_cannot_escape_transaction(tmp_path, name):
    with pytest.raises(ValueError), OutputTransaction(tmp_path) as output:
        output.publish([name], CancellationToken())
    assert not list(tmp_path.iterdir())


def test_publication_works_when_system_temp_is_on_another_volume(tmp_path, monkeypatch):
    import errno
    import os
    import tempfile

    destination = tmp_path / "destination-volume"
    destination.mkdir()
    system_temp = tmp_path / "system-volume"
    system_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_temp))
    real_link = os.link

    def volume(path):
        return "destination" if destination in Path(path).resolve().parents else "system"

    def link_with_volume_boundary(source, target):
        if volume(source) != volume(target):
            raise OSError(errno.EXDEV, "Cross-volume hard link")
        real_link(source, target)

    monkeypatch.setattr(os, "link", link_with_volume_boundary)
    with OutputTransaction(destination) as output:
        (output.staging / "result").write_bytes(b"complete")
        output.publish(["result"], CancellationToken())
    assert (destination / "result").read_bytes() == b"complete"
    assert list(system_temp.iterdir()) == []


def test_rollback_permission_failure_is_reported_as_incomplete_cleanup(tmp_path, monkeypatch):
    original_unlink = Path.unlink

    def locked(path, *args, **kwargs):
        if path == tmp_path / "first":
            raise PermissionError("Output is locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    with pytest.raises(PermissionError), OutputTransaction(tmp_path) as output:
        for name in ("first", "second"):
            (output.staging / name).write_bytes(b"result")
        output.publish(["first", "second"], CancellationToken())
        raise ConversionCancelled()
    assert (tmp_path / "first").read_bytes() == b"result"
    assert not (tmp_path / "second").exists()


def test_valid_dotted_basename_is_not_rejected(tmp_path):
    with OutputTransaction(tmp_path) as output:
        (output.staging / "XX.XX").write_bytes(b"complete")
        paths = output.publish(["XX.XX"], CancellationToken())
    assert paths[0].read_bytes() == b"complete"
