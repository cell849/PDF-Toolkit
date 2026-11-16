"""Abandoned staging recovery must never touch originals or published outputs."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_pdf_toolkit.core import recovery
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.output import OutputTransaction


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "state"))
    # macOS deliberately uses its standard application support directory.
    monkeypatch.setattr(recovery, "_state_directory", lambda: tmp_path / "state" / "recovery")


def abandon(tmp_path):
    transaction = OutputTransaction(tmp_path)
    (transaction.staging / "draft.pdf").write_bytes(b"unfinished")
    # Simulate losing the owner without invoking normal transaction cleanup.
    transaction._temp._finalizer.detach()
    transaction._journal.close(completed=False)
    return transaction


def test_active_jobs_are_not_recoverable_even_in_same_process(tmp_path):
    with OutputTransaction(tmp_path) as first, OutputTransaction(tmp_path) as second:
        (first.staging / "draft.pdf").write_bytes(b"first")
        (second.staging / "draft.pdf").write_bytes(b"second")
        assert recovery.has_recovery_records()
        assert recovery.list_recoverable() == ()
        assert first.staging.exists() and second.staging.exists()
    assert not recovery.has_recovery_records()


def test_cleanup_only_deletes_registered_staging_and_keeps_published_links(tmp_path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"original")
    unknown = tmp_path / ".pdf-toolkit-unknown"
    unknown.mkdir()
    (unknown / "keep.pdf").write_bytes(b"unknown")
    transaction = OutputTransaction(tmp_path)
    (transaction.staging / "published.pdf").write_bytes(b"published")
    transaction.publish(["published.pdf"], CancellationToken())
    (transaction.staging / "draft.pdf").write_bytes(b"unfinished")
    transaction._temp._finalizer.detach()
    transaction._journal.close(completed=False)
    records = recovery.list_recoverable()
    assert len(records) == 1
    assert records[0].possible_incomplete_batch
    assert records[0].published_names == ("published.pdf",)
    recovery.cleanup(records[0])
    assert not transaction.staging.exists()
    assert original.read_bytes() == b"original"
    assert (tmp_path / "published.pdf").read_bytes() == b"published"
    assert (unknown / "keep.pdf").read_bytes() == b"unknown"
    assert recovery.list_recoverable() == ()


def test_corrupt_oversized_and_forged_journals_are_never_cleanup_candidates(tmp_path):
    transaction = abandon(tmp_path)
    path = transaction._journal.path
    valid = path.read_bytes()
    for payload in (b"not json", b"x" * (recovery._MAX_JOURNAL_BYTES + 1), b"[]"):
        path.write_bytes(payload)
        assert recovery.list_recoverable() == ()
        assert transaction.staging.exists()
    path.write_bytes(valid)
    forged = json.loads(valid)
    forged["staging"] = str(tmp_path)
    forged["output_directory"] = str(tmp_path.parent)
    path.write_text(json.dumps(forged))
    assert recovery.list_recoverable() == ()
    assert (transaction.staging / "draft.pdf").read_bytes() == b"unfinished"


@pytest.mark.skipif(os.name == "nt", reason="Creating symlinks requires Windows privileges")
def test_symlinked_staging_and_contents_are_refused(tmp_path):
    original = tmp_path / "original.pdf"
    original.write_bytes(b"original")
    transaction = abandon(tmp_path)
    record = recovery.list_recoverable()[0]
    link = transaction.staging / "linked.pdf"
    link.symlink_to(original)
    assert recovery.list_recoverable() == ()
    with pytest.raises(recovery.RecoveryError):
        recovery.cleanup(record)
    link.unlink()
    moved = tmp_path / "moved"
    transaction.staging.rename(moved)
    transaction.staging.symlink_to(moved, target_is_directory=True)
    assert recovery.list_recoverable() == ()
    with pytest.raises(recovery.RecoveryError):
        recovery.cleanup(record)
    assert original.read_bytes() == b"original"
    assert (moved / "draft.pdf").read_bytes() == b"unfinished"


def test_cleanup_revalidates_record_and_lock_after_user_confirmation(tmp_path):
    transaction = abandon(tmp_path)
    record = recovery.list_recoverable()[0]
    lock = recovery._Lock(transaction._journal.lock_path)
    try:
        with pytest.raises(recovery.RecoveryError):
            recovery.cleanup(record)
        assert transaction.staging.exists()
    finally:
        lock.close()
    (transaction.staging / "new.pdf").write_bytes(b"new")
    with pytest.raises(recovery.RecoveryError, match="changed"):
        recovery.cleanup(record)
    assert transaction.staging.exists()


def test_unexpected_nested_directory_is_left_alone(tmp_path):
    transaction = abandon(tmp_path)
    (transaction.staging / "foreign").mkdir()
    assert recovery.list_recoverable() == ()
    assert (transaction.staging / "draft.pdf").exists()


def test_abrupt_exit_is_recoverable_in_restarted_process(tmp_path):
    # Spawn real independent processes so native lock lifetime, hard links, and
    # os._exit behavior are exercised rather than modeled through PID checks.
    state = tmp_path / "subprocess-state"
    env = dict(os.environ, XDG_STATE_HOME=str(state), LOCALAPPDATA=str(state))
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    code = """
import os, sys
from pathlib import Path
from local_pdf_toolkit.core.output import OutputTransaction
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core import recovery
recovery._state_directory = lambda: Path(sys.argv[2])
root = Path(sys.argv[1])
tx = OutputTransaction(root)
(tx.staging / "first.pdf").write_bytes(b"first")
(tx.staging / "second.pdf").write_bytes(b"second")
real_link = os.link
def crash_on_second(source, destination):
    if Path(destination).name == "second.pdf":
        os._exit(23)
    real_link(source, destination)
os.link = crash_on_second
tx.publish(["first.pdf", "second.pdf"], CancellationToken())
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), str(state)],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 23, result.stderr.decode()
    restart = """
import sys
from pathlib import Path
from local_pdf_toolkit.core import recovery
recovery._state_directory = lambda: Path(sys.argv[1])
records = recovery.list_recoverable()
assert len(records) == 1
assert records[0].possible_incomplete_batch
assert records[0].published_names == ("first.pdf", "second.pdf")
recovery.cleanup(records[0])
assert recovery.list_recoverable() == ()
"""
    result = subprocess.run(
        [sys.executable, "-c", restart, str(state)],
        env=env,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert (tmp_path / "first.pdf").read_bytes() == b"first"
    assert not (tmp_path / "second.pdf").exists()
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_other_app_instance_cannot_recover_running_owner(tmp_path):
    state = tmp_path / "shared-registry"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    owner = """
import sys
from pathlib import Path
from local_pdf_toolkit.core.output import OutputTransaction
from local_pdf_toolkit.core import recovery
recovery._state_directory = lambda: Path(sys.argv[2])
with OutputTransaction(Path(sys.argv[1])) as tx:
    (tx.staging / "draft.pdf").write_bytes(b"still running")
    print("ready", flush=True)
    sys.stdin.readline()
"""
    inspector = """
import sys
from pathlib import Path
from local_pdf_toolkit.core import recovery
recovery._state_directory = lambda: Path(sys.argv[1])
assert recovery.has_recovery_records()
assert recovery.list_recoverable() == ()
"""
    with subprocess.Popen(
        [sys.executable, "-c", owner, str(tmp_path), str(state)],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            # The reader thread keeps a failed child from blocking the suite forever.
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(process.stdout.readline)
                try:
                    assert future.result(timeout=10).strip() == "ready"
                except BaseException:
                    process.kill()
                    raise
            result = subprocess.run(
                [sys.executable, "-c", inspector, str(state)],
                env=env,
                capture_output=True,
                timeout=15,
            )
            assert result.returncode == 0, result.stderr.decode()
            assert len(list(tmp_path.glob(".pdf-toolkit-*"))) == 1
        finally:
            process.communicate("done\n", timeout=10)
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_cleanup_failure_keeps_ownership_for_retry(tmp_path, monkeypatch):
    transaction = abandon(tmp_path)
    record = recovery.list_recoverable()[0]
    real_unlink = os.unlink

    def locked(path, *args, **kwargs):
        if Path(path).name == "draft.pdf":
            raise PermissionError("injected locked staging file")
        return real_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", locked)
        with pytest.raises(recovery.RecoveryError, match="locked staging"):
            recovery.cleanup(record)
    assert transaction._journal.path.exists()
    assert recovery.list_recoverable() == (record,)
    recovery.cleanup(record)
    assert not transaction.staging.exists()
