"""Explicit registration and discovery of trusted conversion adapters."""

import re

from local_pdf_toolkit.core.contracts import Converter, ConverterSpec
from local_pdf_toolkit.core.formats import FileFormat


class ConverterRegistry:
    """Register at startup; no filesystem scanning, network discovery or plugins."""

    def __init__(self) -> None:
        self._converters: dict[str, Converter] = {}

    def register(self, converter: Converter) -> None:
        spec = converter.spec
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*", spec.operation_id):
            raise ValueError("Operation IDs must have the form 'pdf.to_jpeg'.")
        if not spec.label.strip() or not spec.input_formats or not spec.output_formats:
            raise ValueError("A converter needs a label, input formats and output formats.")
        names = [option.name for option in spec.options]
        if any(not name.strip() for name in names) or len(names) != len(set(names)):
            raise ValueError("Option names must be nonempty and unique within a converter.")
        if spec.operation_id in self._converters:
            raise ValueError(f"Operation already registered: {spec.operation_id}")
        self._converters[spec.operation_id] = converter

    def get(self, operation_id: str) -> Converter:
        """Raise KeyError for an unregistered operation; never silently fall back."""
        return self._converters[operation_id]

    def list_operations(self, input_format: FileFormat | None = None) -> tuple[ConverterSpec, ...]:
        return tuple(
            converter.spec
            for converter in self._converters.values()
            if input_format is None or input_format in converter.spec.input_formats
        )
