from dataclasses import replace

import pytest

from local_pdf_toolkit.core.contracts import OptionDefinition
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.registry import ConverterRegistry


def test_registry_lists_filters_and_resolves_test_converter(test_converter):
    registry = ConverterRegistry()
    assert registry.list_operations() == ()
    registry.register(test_converter)
    assert registry.list_operations() == (test_converter.spec,)
    assert registry.list_operations(FileFormat.PDF) == (test_converter.spec,)
    assert registry.list_operations(FileFormat.JPEG) == ()
    assert registry.get("test.noop") is test_converter


def test_duplicate_registration_does_not_replace_converter(test_converter):
    registry = ConverterRegistry()
    registry.register(test_converter)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(test_converter)
    assert registry.get("test.noop") is test_converter


@pytest.mark.parametrize(
    "changes",
    [
        {"operation_id": "not an operation"},
        {"input_formats": ()},
        {"output_formats": ()},
        {"label": " "},
        {"options": (OptionDefinition("dpi", "DPI", 150, "Resolution"),) * 2},
    ],
)
def test_invalid_capability_is_rejected(test_converter, changes):
    test_converter.spec = replace(test_converter.spec, **changes)
    registry = ConverterRegistry()
    with pytest.raises(ValueError):
        registry.register(test_converter)
    assert registry.list_operations() == ()


def test_unknown_operation_is_explicit():
    with pytest.raises(KeyError):
        ConverterRegistry().get("pdf.to_jpeg")
