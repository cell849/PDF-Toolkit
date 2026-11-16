"""Numbered batch copies with a pure naming preview and exclusive publication."""

import os
import stat
import tempfile
import zipfile
from pathlib import Path

from local_pdf_toolkit.converters.file_probe import FileProbeConverter
from local_pdf_toolkit.converters.inspector import SUPPORTED
from local_pdf_toolkit.converters.named_output import _validate_name
from local_pdf_toolkit.converters.pdf_images import MAX_INPUT_BYTES
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

_MAX_BATCH = 10000
_MAX_NUMBER = 99999999
_DEFAULTS = {"base_name": "", "prefix": "", "suffix": "", "start": 1, "digits": 3}


def _options(options):
    if set(options) - _DEFAULTS.keys():
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown batch naming option.")
    values = _DEFAULTS | dict(options)
    for key in ("base_name", "prefix", "suffix"):
        value = values[key]
        if not isinstance(value, str):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Naming fields must be text.")
        if value:
            # Prefix/suffix spaces are useful; validate them within a filename.
            _validate_name(value if key == "base_name" else "x" + value + "x")
    for key, maximum in (("start", _MAX_NUMBER), ("digits", 8)):
        value = values[key]
        if type(value) is not int or not 1 <= value <= maximum:
            raise ConversionError(
                ErrorCode.INVALID_OPTIONS,
                "Use a positive starting number up to 99999999 and 1–8 number digits.",
            )
    return values


def _paths(paths):
    if not isinstance(paths, tuple | list) or not 1 <= len(paths) <= _MAX_BATCH:
        raise ConversionError(ErrorCode.INVALID_INPUT, "Choose between 1 and 10000 files.")
    try:
        result = tuple(Path(path) for path in paths)
    except TypeError as exc:
        raise ConversionError(ErrorCode.INVALID_INPUT, "Choose local file paths.") from exc
    identities = [os.path.abspath(path).casefold() for path in result]
    if len(set(identities)) != len(result):
        raise ConversionError(ErrorCode.INVALID_INPUT, "Choose each input file only once.")
    return result


def plan_names(paths, options):
    """Return the exact ordered output filenames without reading or changing files."""
    paths, values = _paths(paths), _options(options)
    if values["start"] + len(paths) - 1 > _MAX_NUMBER:
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Numbering exceeds 99999999.")
    names = []
    for number, path in enumerate(paths, values["start"]):
        stem = values["base_name"] or path.stem
        name = (
            f"{values['prefix']}{stem}{values['suffix']}-{number:0{values['digits']}d}{path.suffix}"
        )
        _validate_name(name)
        names.append(name)
    if len({name.casefold() for name in names}) != len(names):
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Output filenames must be unique.")
    return tuple(names)


def _signature(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _source_stat(path):
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode) or not 0 < value.st_size <= MAX_INPUT_BYTES:
        raise ConversionError(
            ErrorCode.INVALID_INPUT, "Choose regular, nonempty files below 512 MiB; no shortcuts."
        )
    return value


def _inspect(path, token=None):
    try:
        with tempfile.TemporaryDirectory(prefix="pdf-toolkit-rename-check-") as folder:
            details = FileProbeConverter()._inspect(path, Path(folder), token)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ConversionError(ErrorCode.INVALID_INPUT, "Cannot read or parse this input.") from exc
    kind = FileFormat(details["format"])
    if kind not in SUPPORTED:
        raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, "This file type is not supported.")
    return kind


class BatchRenameConverter:
    spec = ConverterSpec(
        "file.rename_copies",
        "Batch rename copies",
        SUPPORTED,
        SUPPORTED,
        options=(
            OptionDefinition(
                "base_name", "New name", "", "Leave blank to keep each original name."
            ),
            OptionDefinition("prefix", "Prefix", "", "Text before the name."),
            OptionDefinition("suffix", "Suffix", "", "Text after the name, before the number."),
            OptionDefinition(
                "start",
                "Start number",
                1,
                "Number files in their displayed order.",
                minimum=1,
                maximum=_MAX_NUMBER,
            ),
            OptionDefinition(
                "digits",
                "Number digits",
                3,
                "Minimum number width; pad with zeroes.",
                minimum=1,
                maximum=8,
            ),
        ),
        limitations=(
            "Creates byte-identical copies; originals and file extensions stay unchanged.",
            "Metadata remains. Unsupported or encrypted files must be handled separately.",
        ),
        input_mode="multiple",
    )

    def validate_options(self, options):
        return _options(options)

    def validate_input(self, input_path):
        path = Path(input_path)
        try:
            _source_stat(path)
            return _inspect(path)
        except OSError as exc:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Cannot read this input file.") from exc

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        paths = _paths(input_path)
        names = plan_names(paths, options)
        cancel_token.raise_if_cancelled()
        try:
            signatures = [_signature(_source_stat(path)) for path in paths]
            if len({signature[:2] for signature in signatures}) != len(paths):
                raise ConversionError(ErrorCode.INVALID_INPUT, "Choose each input file only once.")
            directory = Path(output_dir).resolve(strict=True)
            if any(len(str(directory / name).encode("utf-16-le")) // 2 > 259 for name in names):
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "Use shorter names or a shorter output folder path."
                )
            planned = {name.casefold() for name in names}
            if any(entry.name.casefold() in planned for entry in directory.iterdir()):
                raise FileExistsError
            with OutputTransaction(directory) as output:
                for index, (source, name, signature) in enumerate(
                    zip(paths, names, signatures, strict=True)
                ):
                    cancel_token.raise_if_cancelled()
                    target = output.staging / name
                    with source.open("rb") as original, target.open("xb") as copy:
                        if _signature(os.fstat(original.fileno())) != signature:
                            raise ConversionError(
                                ErrorCode.INVALID_INPUT, "An input file changed; add it again."
                            )
                        count = 0
                        while chunk := original.read(1024 * 1024):
                            cancel_token.raise_if_cancelled()
                            count += len(chunk)
                            if count > MAX_INPUT_BYTES:
                                raise ConversionError(
                                    ErrorCode.INVALID_INPUT, "An input file exceeds 512 MiB."
                                )
                            copy.write(chunk)
                        if (
                            count != signature[2]
                            or _signature(os.fstat(original.fileno())) != signature
                        ):
                            raise ConversionError(
                                ErrorCode.INVALID_INPUT, "An input file changed; add it again."
                            )
                    # Parse the snapshot that will be published, not the mutable original.
                    _inspect(target, cancel_token)
                    progress(Progress(index + 1, len(paths)))
                for path, signature in zip(paths, signatures, strict=True):
                    if _signature(_source_stat(path)) != signature:
                        raise ConversionError(
                            ErrorCode.INVALID_INPUT, "An input file changed; add it again."
                        )
                return output.publish(list(names), cancel_token)
        except FileExistsError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "An output with this name already exists. Choose another name.",
            ) from exc
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "Cannot read the inputs or write copies to this output folder.",
            ) from exc
