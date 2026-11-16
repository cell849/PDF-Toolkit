"""Generate three same-resolution candidates for the existing visual comparison UI."""

from pathlib import Path

from local_pdf_toolkit.converters.images import FORMATS, opaque, open_image, safe_stem
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction


class ImageComparisonConverter:
    spec = ConverterSpec(
        "image.compare_formats",
        "Compare image formats",
        tuple(FORMATS.values()),
        (FileFormat.JPEG, FileFormat.PNG, FileFormat.WEBP),
        (
            OptionDefinition(
                "quality",
                "JPEG / WebP quality",
                85,
                "Quality numbers are encoder settings, not a perceptual score.",
                minimum=1,
                maximum=100,
            ),
        ),
        (
            "Creates JPEG, PNG and WebP candidates at the same pixel dimensions. "
            "Use Compare to inspect each result and its exact size. JPEG uses a white "
            "background for transparency. Metadata is removed. Originals stay unchanged; "
            "multi-frame images are rejected. All three candidates are saved.",
        ),
    )

    def validate_input(self, path):
        with open_image(path) as image:
            return FORMATS[image.format]

    def validate_options(self, options):
        quality = options.get("quality", 85)
        if set(options) - {"quality"} or type(quality) is not int or not 1 <= quality <= 100:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Choose quality from 1 to 100.")
        return {"quality": quality}

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        quality = self.validate_options(options)["quality"]
        cancel_token.raise_if_cancelled()
        with open_image(input_path) as image, OutputTransaction(Path(output_dir)) as output:
            names = []
            for index, (kind, extension) in enumerate(
                (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"))
            ):
                cancel_token.raise_if_cancelled()
                converted = opaque(image) if kind == "JPEG" else image.convert("RGBA")
                with converted:
                    converted.info.clear()
                    name = f"{safe_stem(input_path)}_compare.{extension}"
                    converted.save(
                        output.staging / name,
                        format=kind,
                        **({"optimize": True} if kind == "PNG" else {"quality": quality}),
                    )
                names.append(name)
                progress(Progress(index + 1, 3))
            return output.publish(names, cancel_token)
