"""Shared adapter capabilities, validation, progress and cancellation contract."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

from local_pdf_toolkit.core.errors import ConversionCancelled
from local_pdf_toolkit.core.formats import FileFormat

type OptionValue = str | int | float | bool | None


@dataclass(frozen=True)
class OptionDefinition:
    """Declarative UI metadata; adapters enforce their own documented constraints."""

    name: str
    label: str
    default: OptionValue
    description: str
    choices: tuple[OptionValue, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class ConverterSpec:
    operation_id: str
    label: str
    input_formats: tuple[FileFormat, ...]
    output_formats: tuple[FileFormat, ...]
    options: tuple[OptionDefinition, ...] = ()
    limitations: tuple[str, ...] = ()
    input_mode: str = "single"


@dataclass(frozen=True)
class Progress:
    """Page counts when measurable; total=None denotes indeterminate progress."""

    completed: int = 0
    total: int | None = None

    def __post_init__(self) -> None:
        if self.completed < 0:
            raise ValueError("Completed count cannot be negative.")
        if self.total is not None and (self.total < 0 or self.completed > self.total):
            raise ValueError("Progress must satisfy 0 <= completed <= total.")


type ProgressCallback = Callable[[Progress], None]


class CancellationToken:
    """Thread-safe cooperative cancellation, checked between work units by adapters."""

    def __init__(self, event=None) -> None:
        self._event = event if event is not None else Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise ConversionCancelled()


class Converter(Protocol):
    """A trusted, code-registered adapter; never load executable document plugins.

    validate_input verifies actual format, parser acceptance and encryption.
    validate_options rejects unknown/invalid values and supplies explicit defaults.
    convert must also validate, preserve the input, avoid unapproved overwrites,
    stage outputs, clean incomplete outputs on error/cancellation, and raise
    ConversionError for failures. No silent partial success. It runs off the UI
    thread; progress callbacks must not touch widgets directly.

    input_mode="multiple" operations accept an ordered tuple of input paths.
    """

    @property
    def spec(self) -> ConverterSpec: ...

    def validate_input(self, input_path: Path) -> FileFormat: ...

    def validate_options(self, options: Mapping[str, OptionValue]) -> dict[str, OptionValue]: ...

    def convert(
        self,
        input_path: Path | tuple[Path, ...],
        output_dir: Path,
        options: Mapping[str, OptionValue],
        progress: ProgressCallback,
        cancel_token: CancellationToken,
    ) -> tuple[Path, ...]: ...
