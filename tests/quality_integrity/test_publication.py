"""Actual filesystem collisions, concurrent publishers, and injected publication faults."""

import errno
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from local_pdf_toolkit.core import output as output_module
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled
from local_pdf_toolkit.core.output import OutputTransaction


@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EACCES, errno.EIO])
def test_partial_publication_failure_removes_only_owned_files(tmp_path, monkeypatch, error_number):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"original bytes must survive")
    real_link = os.link

    def fail_second_link(source, destination):
        if Path(destination).name == "second.pdf":
            raise OSError(error_number, "injected second-publication failure")
        real_link(source, destination)

    monkeypatch.setattr(output_module.os, "link", fail_second_link)
    with pytest.raises(OSError) as error, OutputTransaction(tmp_path) as transaction:
        for name in ("first.pdf", "second.pdf", "third.pdf"):
            (transaction.staging / name).write_bytes(name.encode())
        transaction.publish(["first.pdf", "second.pdf", "third.pdf"], CancellationToken())
    assert error.value.errno == error_number
    assert list(tmp_path.iterdir()) == [original]
    assert original.read_bytes() == b"original bytes must survive"


def test_cancellation_between_publications_rolls_back_all_owned_files(tmp_path, monkeypatch):
    real_link = os.link
    token = CancellationToken()

    def cancel_after_link(source, destination):
        real_link(source, destination)
        token.cancel()

    monkeypatch.setattr(output_module.os, "link", cancel_after_link)
    with pytest.raises(ConversionCancelled), OutputTransaction(tmp_path) as transaction:
        (transaction.staging / "first.pdf").write_bytes(b"first")
        (transaction.staging / "second.pdf").write_bytes(b"second")
        transaction.publish(["first.pdf", "second.pdf"], token)
    assert list(tmp_path.iterdir()) == []


def test_rollback_preserves_concurrent_replacement(tmp_path):
    with pytest.raises(RuntimeError), OutputTransaction(tmp_path) as transaction:
        (transaction.staging / "first.pdf").write_bytes(b"this job")
        transaction.publish(["first.pdf"], CancellationToken())
        (tmp_path / "first.pdf").unlink()
        (tmp_path / "first.pdf").write_bytes(b"foreign replacement")
        raise RuntimeError("injected failure after publication")
    assert (tmp_path / "first.pdf").read_bytes() == b"foreign replacement"
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_concurrent_jobs_have_one_complete_winner(tmp_path):
    barrier = Barrier(2)

    def publish_job(label):
        try:
            with OutputTransaction(tmp_path) as transaction:
                for name in ("first.pdf", "second.pdf"):
                    (transaction.staging / name).write_bytes(label)
                barrier.wait(timeout=5)
                transaction.publish(["first.pdf", "second.pdf"], CancellationToken())
            return "success", label
        except FileExistsError:
            return "collision", label

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish_job, (b"job-a", b"job-b")))
    winners = [label for status, label in results if status == "success"]
    assert len(winners) == 1
    assert sorted(status for status, _ in results) == ["collision", "success"]
    assert (tmp_path / "first.pdf").read_bytes() == winners[0]
    assert (tmp_path / "second.pdf").read_bytes() == winners[0]
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_one_rollback_permission_error_does_not_leave_other_owned_outputs(tmp_path, monkeypatch):
    real_unlink = Path.unlink

    def deny_first_destination(path, *args, **kwargs):
        if path == tmp_path / "first.pdf":
            raise PermissionError("injected independently locked output")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_first_destination)
    with pytest.raises((PermissionError, RuntimeError)), OutputTransaction(tmp_path) as transaction:
        for name in ("first.pdf", "second.pdf", "third.pdf"):
            (transaction.staging / name).write_bytes(name.encode())
        transaction.publish(["first.pdf", "second.pdf", "third.pdf"], CancellationToken())
        raise RuntimeError("injected failure after all publications")
    # The locked path cannot be removed, but independent paths can and must be.
    assert (tmp_path / "first.pdf").exists()
    assert not (tmp_path / "second.pdf").exists()
    assert not (tmp_path / "third.pdf").exists()
    assert not list(tmp_path.glob(".pdf-toolkit-*"))
