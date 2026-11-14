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
        try:
            if kind is not None:
                for path in self._published:
                    staged = self.staging / path.name
                    if path.exists() and path.samefile(staged):
                        path.unlink()
        finally:
            self._temp.cleanup()
