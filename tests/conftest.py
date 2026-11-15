"""Synthetic inputs only; never use personal documents as committed fixtures."""

import os
from pathlib import Path

# Set before importing Qt. Allows the same widget smoke test in Linux and Windows CI.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from local_pdf_toolkit.core.contracts import (  # noqa: E402
    CancellationToken,
    ConverterSpec,
    OptionValue,
    Progress,
    ProgressCallback,
)
from local_pdf_toolkit.core.formats import FileFormat  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class TestOnlyConverter:
    """A no-I/O contract double, never registered in the shipping application."""

    spec = ConverterSpec(
        operation_id="test.noop",
        label="Test operation",
        input_formats=(FileFormat.PDF,),
        output_formats=(FileFormat.PNG,),
    )

    def validate_input(self, input_path: Path) -> FileFormat:
        raise NotImplementedError("The M0 test double does not parse files.")

    def validate_options(self, options) -> dict[str, OptionValue]:
        return dict(options)

    def convert(
        self,
        input_path: Path,
        output_dir: Path,
        options,
        progress: ProgressCallback,
        cancel_token: CancellationToken,
    ) -> tuple[Path, ...]:
        cancel_token.raise_if_cancelled()
        progress(Progress(completed=0, total=0))
        return ()


@pytest.fixture
def test_converter():
    return TestOnlyConverter()


@pytest.fixture
def fixture_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_desktop_preferences(tmp_path):
    """Never read or overwrite a developer's real window/unit preferences."""
    from PySide6.QtCore import QSettings

    previous = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "settings")
    )
    yield
    QSettings.setDefaultFormat(previous)
