"""Apply an explicitly chosen output name without weakening atomic publication."""

import os
import re
import tempfile
import unicodedata
from pathlib import Path

from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.output import OutputTransaction

_DEVICES = {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
_DEVICES.update(f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in "123456789¹²³")
_ALIASES = {"jpeg": {"jpg", "jpeg"}, "tiff": {"tif", "tiff"}}


def _validate_name(name):
    if (
        not isinstance(name, str)
        or not name
        or name != name.strip()
        or name in (".", "..")
        or name.endswith(".")
        or re.search(r'[<>:"/\\|?*]', name)
        or any(unicodedata.category(char) in ("Cc", "Cf", "Cs") for char in name)
    ):
        raise ConversionError(
            ErrorCode.INVALID_OPTIONS,
            "Choose a filename without paths, control characters, or trailing dots/spaces.",
        )
    if name.split(".", 1)[0].rstrip(" .").upper() in _DEVICES:
        raise ConversionError(ErrorCode.INVALID_OPTIONS, "Choose a nonreserved Windows filename.")
    if len(name.encode("utf-16-le")) // 2 > 200:
        raise ConversionError(
            ErrorCode.INVALID_OPTIONS, "Keep the output name below 201 characters."
        )


def normalize_base_name(base_name, output_formats):
    """Remove only a declared output extension; other suffixes remain ordinary text.

    Actual converter extensions are always appended later, so a user-supplied
    suffix cannot change or disguise the format of the resulting file.
    """
    _validate_name(base_name)
    extensions = set()
    for kind in output_formats:
        value = str(kind)
        extensions.update(_ALIASES.get(value, {value}))
    suffix = Path(base_name).suffix
    normalized = base_name[: -len(suffix)] if suffix[1:].lower() in extensions else base_name
    _validate_name(normalized)
    return normalized


def _names(paths, base_name):
    if len(paths) == 1:
        return [base_name + paths[0].suffix]
    documents = [path for path in paths if not path.name.lower().endswith(".report.json")]
    reports = [path for path in paths if path not in documents]
    names = {}
    stems = {}
    for index, path in enumerate(documents, 1):
        stem = base_name if len(documents) == 1 else f"{base_name}-{index}"
        names[path] = stem + path.suffix
        stems[path.stem] = stem
    for index, path in enumerate(reports, 1):
        original_stem = path.name[: -len(".report.json")]
        stem = stems.get(original_stem)
        if stem is None:
            stem = base_name if len(reports) == 1 else f"{base_name}-{index}"
        names[path] = stem + ".report.json"
    result = [names[path] for path in paths]
    if len({name.casefold() for name in result}) != len(result):
        raise ConversionError(ErrorCode.OUTPUT_ERROR, "Generated output names are not unique.")
    return result


class NamedOutputConverter:
    """Picklable adapter which renames only its delegate's completed temporary files.

    Both temporary directories live beside the final outputs. Publication uses
    OutputTransaction's exclusive hard links and rolls back partial publication
    on collisions, errors, and cancellation. Report bytes remain unchanged.
    """

    def __init__(self, delegate, base_name):
        self.delegate = delegate
        self.spec = delegate.spec
        self.base_name = normalize_base_name(base_name, self.spec.output_formats)

    def validate_input(self, input_path):
        return self.delegate.validate_input(input_path)

    def validate_options(self, options):
        return self.delegate.validate_options(options)

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        cancel_token.raise_if_cancelled()
        try:
            directory = Path(output_dir).resolve(strict=True)
            with tempfile.TemporaryDirectory(prefix=".pdf-toolkit-named-", dir=directory) as temp:
                workspace = Path(temp).resolve()
                paths = tuple(
                    Path(path)
                    for path in self.delegate.convert(
                        input_path, workspace, options, progress, cancel_token
                    )
                )
                cancel_token.raise_if_cancelled()
                if not paths:
                    raise ConversionError(ErrorCode.CONVERSION_FAILED, "No outputs were produced.")
                for path in paths:
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or not path.resolve().is_relative_to(workspace)
                    ):
                        raise ConversionError(
                            ErrorCode.OUTPUT_ERROR, "The converter produced an invalid output path."
                        )
                names = _names(paths, self.base_name)
                with OutputTransaction(directory) as output:
                    for path, name in zip(paths, names, strict=True):
                        cancel_token.raise_if_cancelled()
                        os.link(path, output.staging / name)
                    return output.publish(names, cancel_token)
        except FileExistsError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "An output with this name already exists. Choose another name.",
            ) from exc
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR, "Cannot write the named outputs to this folder."
            ) from exc
