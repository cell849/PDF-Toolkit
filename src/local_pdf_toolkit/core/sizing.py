"""Shared file-size targets, using decimal input and whole-byte upper bounds."""

from decimal import ROUND_FLOOR, Decimal

from local_pdf_toolkit.core.contracts import OptionDefinition
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode

TARGET_UNITS = ("KB", "MB", "KiB", "MiB", "percent")
TARGET_OPTIONS = (
    OptionDefinition(
        "target_value",
        "Maximum file size (0 = no target)",
        0.0,
        "An upper bound; percentage uses the original file size.",
        minimum=0,
        maximum=1000000,
    ),
    OptionDefinition("target_unit", "Size unit", "KiB", "KB/MB are decimal units.", TARGET_UNITS),
    OptionDefinition(
        "target_kib",
        "Legacy maximum size (KiB)",
        0,
        "For older callers; cannot be combined with a new size target.",
        minimum=0,
        maximum=1000000,
    ),
    OptionDefinition(
        "allow_downscale",
        "Allow resolution reduction to meet size",
        False,
        "When off, size targeting preserves the selected dimensions or DPI.",
    ),
)


def validate_target_options(options):
    """Validate the shared subset without rejecting a converter's other options."""
    values = {
        definition.name: options.get(definition.name, definition.default)
        for definition in TARGET_OPTIONS
    }
    value, unit, legacy = values["target_value"], values["target_unit"], values["target_kib"]
    if (
        type(value) not in (int, float)
        or not 0 <= value <= 1000000
        or type(unit) is not str
        or unit not in TARGET_UNITS
        or (unit == "percent" and value > 100)
        or type(legacy) is not int
        or not 0 <= legacy <= 1000000
        or type(values["allow_downscale"]) is not bool
        or (value and legacy)
    ):
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid file-size target options.")
    return values


def target_bytes(options, source_size):
    """Return a floored byte limit, or zero only when no target was selected."""
    values = validate_target_options(options)
    if values["target_kib"]:
        return values["target_kib"] * 1024
    value = Decimal(str(values["target_value"]))
    if not value:
        return 0
    unit = values["target_unit"]
    multiplier = {
        "KB": Decimal(1000),
        "MB": Decimal(1000000),
        "KiB": Decimal(1024),
        "MiB": Decimal(1048576),
        "percent": Decimal(source_size) / 100,
    }[unit]
    limit = int((value * multiplier).to_integral_value(rounding=ROUND_FLOOR))
    if limit < 1:
        raise ConversionError(
            ErrorCode.INVALID_OPTIONS, "The selected target is smaller than one byte."
        )
    return limit
