"""Explicit recovery of registered staging folders, never of published outputs.

A kernel file lock is held for the whole transaction. Recovery therefore does not
infer liveness from PIDs (which can be reused), and works across app instances.
Malformed, oversized, missing, linked, or changed ownership records are ignored.
"""

import json
import os
import re
import stat
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_MAX_JOURNAL_BYTES = 128 * 1024
_MAX_JOBS = 4096
_MAX_FILES = 100_000
_MARKER = ".pdf-toolkit-owner"
_JOB_ID = re.compile(r"[0-9a-f]{32}")


class RecoveryError(OSError):
    """Recovery cannot establish exclusive ownership of an abandoned folder."""


@dataclass(frozen=True)
class RecoveryRecord:
    job_id: str
    staging: Path
    output_directory: Path
    created_at: str
    possible_incomplete_batch: bool
    published_names: tuple[str, ...]
    file_count: int
    size_bytes: int


def _state_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "local-pdf-toolkit" / "recovery"


def _plain(path: Path, *, directory: bool = False) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise RecoveryError("Recovery refuses symbolic links or reparse points.")
    valid = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not valid:
        raise RecoveryError("Recovery encountered an unexpected file type.")
    return info


def _registry(*, create: bool = False) -> Path:
    root = _state_directory().absolute()
    if create:
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
    _plain(root, directory=True)
    if root.resolve(strict=True) != root:
        raise RecoveryError("Recovery registry must not traverse symbolic links.")
    return root


class _Lock:
    def __init__(self, path: Path, *, create: bool = False):
        flags = os.O_RDWR | (os.O_CREAT | os.O_EXCL if create else 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        self.fd = os.open(path, flags, 0o600)
        try:
            _plain(path)
            if create:
                os.write(self.fd, b"1")
            if os.name == "nt":
                import msvcrt

                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        if self.fd is not None:
            # Closing releases the kernel lock, including after an abrupt crash.
            os.close(self.fd)
            self.fd = None


def _read(path: Path) -> dict:
    _plain(path)
    with path.open("rb") as stream:
        raw = stream.read(_MAX_JOURNAL_BYTES + 1)
    if len(raw) > _MAX_JOURNAL_BYTES:
        raise RecoveryError("Recovery journal is too large.")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise RecoveryError("Invalid recovery journal.")
    return document


def _valid_name(name) -> bool:
    return (
        isinstance(name, str)
        and 0 < len(name) <= 255
        and name not in (".", "..", _MARKER)
        and not any(char in name for char in ("/", "\\", "\0", ":"))
    )


class StagingJournal:
    """Internal transaction ownership journal; callers must close it in finally."""

    def __init__(self, staging: Path):
        self.root = _registry(create=True)
        self.job_id = uuid.uuid4().hex
        self.path = self.root / f"{self.job_id}.json"
        self.lock_path = self.root / f"{self.job_id}.lock"
        self.lock = _Lock(self.lock_path, create=True)
        try:
            info = _plain(staging, directory=True)
            marker = staging / _MARKER
            with marker.open("x", encoding="ascii") as stream:
                stream.write(self.job_id)
                stream.flush()
                os.fsync(stream.fileno())
            self.document = {
                "version": 1,
                "job_id": self.job_id,
                "staging": str(staging),
                "output_directory": str(staging.parent),
                "device": info.st_dev,
                "inode": info.st_ino,
                "created_at": datetime.now(UTC).isoformat(),
                "publication_started": False,
                "published_names": [],
            }
            self._write()
        except BaseException:
            self.close(completed=True)
            raise

    def _write(self):
        temporary = self.root / f"{self.job_id}.pending"
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.document, stream, ensure_ascii=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def before_publish(self, names: list[str]):
        # Intent is durable before the first link; a crash between link and journal
        # update must still warn the user that a batch may have been interrupted.
        self.document["publication_started"] = True
        self.document["published_names"] = [name for name in names[:128] if _valid_name(name)]
        self._write()

    def close(self, *, completed: bool):
        try:
            if completed:
                self.path.unlink(missing_ok=True)
        finally:
            self.lock.close()
        if completed:
            self.lock_path.unlink(missing_ok=True)


def _inspect(root: Path, job_id: str) -> RecoveryRecord:
    document = _read(root / f"{job_id}.json")
    if document.get("version") != 1 or document.get("job_id") != job_id:
        raise RecoveryError("Unrecognized recovery journal.")
    stage = Path(document["staging"])
    output = Path(document["output_directory"])
    if (
        not stage.is_absolute()
        or not output.is_absolute()
        or stage.parent != output
        or not stage.name.startswith(".pdf-toolkit-")
        or stage.resolve(strict=True) != stage
        or output.resolve(strict=True) != output
    ):
        raise RecoveryError("Recovery staging path is unsafe.")
    _plain(output, directory=True)
    info = _plain(stage, directory=True)
    if (info.st_dev, info.st_ino) != (document.get("device"), document.get("inode")):
        raise RecoveryError("Recovery staging folder has changed.")
    marker = stage / _MARKER
    _plain(marker)
    with marker.open("rb") as stream:
        if stream.read(33) != job_id.encode("ascii"):
            raise RecoveryError("Staging ownership marker does not match.")
    count = size = 0
    # Staging is flat by contract. Unknown directories, links, and device files are
    # deliberately left alone; recovery never recursively follows their contents.
    for entry in stage.iterdir():
        entry_info = _plain(entry)
        count += 1
        size += entry_info.st_size
        if count > _MAX_FILES:
            raise RecoveryError("Recovery folder contains too many files.")
    names = document.get("published_names")
    if (
        not isinstance(names, list)
        or len(names) > 128
        or not all(_valid_name(name) for name in names)
        or not isinstance(document.get("created_at"), str)
        or type(document.get("publication_started")) is not bool
    ):
        raise RecoveryError("Invalid recovery publication details.")
    return RecoveryRecord(
        job_id,
        stage,
        output,
        document["created_at"],
        document["publication_started"],
        tuple(names),
        count - 1,
        size - marker.stat().st_size,
    )


def list_recoverable() -> tuple[RecoveryRecord, ...]:
    """Inspect known, unlocked staging jobs. Never delete anything automatically."""
    try:
        root = _registry()
    except OSError:
        return ()
    records = []
    for index, path in enumerate(root.iterdir()):
        if index >= _MAX_JOBS * 3:
            break
        if path.suffix != ".json" or not _JOB_ID.fullmatch(path.stem):
            continue
        lock = None
        try:
            lock = _Lock(root / f"{path.stem}.lock")
            records.append(_inspect(root, path.stem))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        finally:
            if lock is not None:
                lock.close()
    return tuple(records)


def cleanup(record: RecoveryRecord) -> None:
    """Remove one explicitly selected abandoned stage; keep all published outputs.

    Re-check the journal, lock, directory identity and marker after confirmation.
    Refuse stale records or unfamiliar contents rather than guessing ownership.
    """
    if not _JOB_ID.fullmatch(record.job_id):
        raise RecoveryError("Invalid recovery identifier.")
    lock = None
    try:
        root = _registry()
        lock = _Lock(root / f"{record.job_id}.lock")
        fresh = _inspect(root, record.job_id)
        if fresh != record:
            raise RecoveryError("Recovery folder changed; inspect abandoned jobs again.")
        # Use a directory descriptor on POSIX so replacing an ancestor cannot
        # redirect file removal into a different directory.
        if os.name != "nt":
            descriptor = os.open(fresh.staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                info = os.fstat(descriptor)
                current = _plain(fresh.staging, directory=True)
                if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino):
                    raise RecoveryError("Recovery folder changed.")
                for name in os.listdir(descriptor):
                    entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if not stat.S_ISREG(entry.st_mode):
                        raise RecoveryError("Recovery folder contains an unsafe entry.")
                names = os.listdir(descriptor)
                for name in names:
                    if name != _MARKER:
                        os.unlink(name, dir_fd=descriptor)
                # Keep ownership evidence if an ordinary file cannot be removed.
                os.unlink(_MARKER, dir_fd=descriptor)
            finally:
                os.close(descriptor)
        else:
            for path in fresh.staging.iterdir():
                if path.name != _MARKER:
                    _plain(path)
                    path.unlink()
            (fresh.staging / _MARKER).unlink()
        fresh.staging.rmdir()
        (root / f"{record.job_id}.json").unlink()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RecoveryError(f"Could not safely clean abandoned staging: {exc}") from exc
    finally:
        if lock is not None:
            lock.close()
    (root / f"{record.job_id}.lock").unlink(missing_ok=True)


def has_recovery_records() -> bool:
    """Cheap startup hint: inspect registry names only, including possibly active jobs."""
    try:
        root = _registry()
        for index, path in enumerate(root.iterdir()):
            if index >= _MAX_JOBS * 3:
                break
            if path.suffix == ".json" and _JOB_ID.fullmatch(path.stem):
                return True
    except OSError:
        pass
    return False
