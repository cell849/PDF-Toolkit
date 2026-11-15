"""Stage a job beside its outputs; publish without replacing existing files."""

import os
import tempfile
from pathlib import Path


class OutputTransaction:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve(strict=True)
        if not self.directory.is_dir():
            raise NotADirectoryError(str(directory))
        self._temp = tempfile.TemporaryDirectory(prefix=".pdf-toolkit-", dir=self.directory)
        self.staging = Path(self._temp.name)
        self._published: list[Path] = []

    def publish(self, names: list[str], cancel_token) -> tuple[Path, ...]:
        for name in names:
            if Path(name).name != name or name in (".", ".."):
                raise ValueError("Invalid output name.")
            cancel_token.raise_if_cancelled()
            destination = self.directory / name
            # Same-filesystem hard links are atomic and fail if a file already exists.
            # Never fall back to replace/rename that could overwrite another job's file.
            os.link(self.staging / name, destination)
            self._published.append(destination)
        cancel_token.raise_if_cancelled()
        return tuple(self._published)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        cleanup_error = None
        try:
            if kind is not None:
                for path in self._published:
                    try:
                        staged = self.staging / path.name
                        if path.samefile(staged):
                            path.unlink()
                    except FileNotFoundError:
                        # Another process may already have removed the output.
                        pass
                    except OSError as exc:
                        # A locked output must not prevent cleanup of other files.
                        if cleanup_error is None:
                            cleanup_error = exc
        finally:
            self._temp.cleanup()
        if cleanup_error is not None:
            cleanup_error.add_note("Incomplete outputs remain; check the output folder.")
            raise cleanup_error
