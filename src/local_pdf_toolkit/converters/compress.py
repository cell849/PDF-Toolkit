"""Lossless PDF cleanup or explicitly lossy rasterized target-size compression."""

import math
from pathlib import Path

import pymupdf

from local_pdf_toolkit.converters.images import safe_stem
from local_pdf_toolkit.converters.pdf_images import MAX_PIXELS, PdfImagesConverter
from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction
from local_pdf_toolkit.core.sizing import TARGET_OPTIONS, target_bytes, validate_target_options


class PdfCompressConverter:
    spec = ConverterSpec(
        "pdf.compress",
        "Compress PDF",
        (FileFormat.PDF,),
        (FileFormat.PDF,),
        (
            OptionDefinition(
                "mode",
                "Compression mode",
                "lossless",
                "Rasterized mode discards selectable text, forms and links.",
                ("lossless", "rasterized"),
            ),
            OptionDefinition(
                "dpi",
                "Raster resolution (DPI)",
                150,
                "Used only in rasterized mode (10–1200).",
                minimum=10,
                maximum=1200,
            ),
        )
        + TARGET_OPTIONS,
        (
            "Lossless cleanup cannot guarantee a smaller file. Rasterized mode is lossy "
            "and removes text selection, links and forms. "
            "Size targets are upper bounds, not exact sizes.",
        ),
    )

    def validate_input(self, path):
        return PdfImagesConverter(FileFormat.PNG).validate_input(path)

    def validate_options(self, options):
        result = {d.name: options.get(d.name, d.default) for d in self.spec.options}
        result.update(validate_target_options(options))
        if (
            set(options) - result.keys()
            or result["mode"] not in ("lossless", "rasterized")
            or type(result["dpi"]) is not int
            or not 10 <= result["dpi"] <= 1200
        ):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid compression options.")
        return result

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        opts = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        try:
            with (
                PdfImagesConverter(FileFormat.PNG)._open(Path(input_path)) as source,
                OutputTransaction(Path(output_dir)) as output,
            ):
                name = f"{safe_stem(input_path)}_compressed.pdf"
                target = target_bytes(opts, Path(input_path).stat().st_size)
                destination = output.staging / name
                if opts["mode"] == "lossless":
                    source.save(
                        destination,
                        garbage=4,
                        deflate=True,
                        deflate_images=True,
                        deflate_fonts=True,
                    )
                    progress(Progress(1, 1))
                else:
                    trials = 16 if opts["allow_downscale"] else 4
                    for trial in range(trials):
                        cancel_token.raise_if_cancelled()
                        destination.unlink(missing_ok=True)
                        dpi = max(10, int(opts["dpi"] * (0.75 ** (trial // 4))))
                        quality = (90, 70, 45, 20)[trial % 4]
                        with pymupdf.open() as document:
                            for index, page in enumerate(source, 1):
                                cancel_token.raise_if_cancelled()
                                pixel_dpi = (
                                    int(
                                        72
                                        * math.sqrt(
                                            MAX_PIXELS / (page.rect.width * page.rect.height)
                                        )
                                    )
                                    - 1
                                )
                                render_dpi = min(dpi, pixel_dpi) if opts["allow_downscale"] else dpi
                                # Native rasters round each dimension up separately. An
                                # area-only estimate is unsafe for very thin/long pages.
                                while render_dpi >= 10 and (
                                    math.ceil(page.rect.width * render_dpi / 72)
                                    * math.ceil(page.rect.height * render_dpi / 72)
                                    > MAX_PIXELS
                                ):
                                    if not opts["allow_downscale"]:
                                        raise ConversionError(
                                            ErrorCode.INVALID_INPUT,
                                            "Page exceeds 40 million pixels. Try a lower DPI.",
                                        )
                                    render_dpi -= 1
                                if render_dpi < 10:
                                    raise ConversionError(
                                        ErrorCode.INVALID_INPUT,
                                        "Page dimensions exceed rendering limits.",
                                    )
                                pixmap = page.get_pixmap(
                                    dpi=render_dpi, colorspace=pymupdf.csRGB, alpha=False
                                )
                                image = pixmap.tobytes("jpeg", jpg_quality=quality)
                                new_page = document.new_page(
                                    width=page.rect.width, height=page.rect.height
                                )
                                new_page.insert_image(new_page.rect, stream=image)
                                del pixmap, image
                                progress(Progress(index, len(source)))
                            document.save(destination, garbage=4, deflate=True)
                        if not target or destination.stat().st_size <= target:
                            break
                if target and destination.stat().st_size > target:
                    raise ConversionError(
                        ErrorCode.INVALID_OPTIONS,
                        "Target size cannot be met. Increase the limit, allow resolution reduction "
                        "or select rasterized mode.",
                    )
                return output.publish([name], cancel_token)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConversionError(ErrorCode.OUTPUT_ERROR, f"Compression failed: {exc}") from exc
