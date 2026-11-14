"""Structured failures for converter adapters and future job handling."""

from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PASSWORD_REQUIRED = "password_required"
    INVALID_OPTIONS = "invalid_options"
    OUTPUT_ERROR = "output_error"
    CANCELLED = "cancelled"
    CONVERSION_FAILED = "conversion_failed"


class ConversionError(Exception):
    """An actionable message plus a stable code; do not include document contents."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ConversionCancelled(ConversionError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.CANCELLED, "Conversion cancelled.")
