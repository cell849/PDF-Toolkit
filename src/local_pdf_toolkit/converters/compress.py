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
                "target_kib",
                "Maximum file size (KiB, 0 = no target)",
                0,
                "Fails if the target cannot be met.",
                minimum=0,
                maximum=1000000,
            ),
            OptionDefinition(
                "dpi",
                "Maximum raster resolution (DPI)",
                150,
                "Used only in rasterized mode.",
                (72, 150, 300),
            ),
        ),
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
        if (
            set(options) - result.keys()
            or result["mode"] not in ("lossless", "rasterized")
            or type(result["dpi"]) is not int
            or result["dpi"] not in (72, 150, 300)
            or type(result["target_kib"]) is not int
            or not 0 <= result["target_kib"] <= 1000000
        ):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid compression options.")
        return result

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        opts = self.validate_options(options)
        target = opts["target_kib"] * 1024
        cancel_token.raise_if_cancelled()
        try:
            with (
                PdfImagesConverter(FileFormat.PNG)._open(Path(input_path)) as source,
                OutputTransaction(Path(output_dir)) as output,
            ):
                name = f"{safe_stem(input_path)}_compressed.pdf"
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
                    for trial in range(16):
                        cancel_token.raise_if_cancelled()
                        destination.unlink(missing_ok=True)
                        dpi = max(36, int(opts["dpi"] * (0.75 ** (trial // 4))))
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
                                render_dpi = min(dpi, pixel_dpi)
                                # Native rasters round each dimension up separately. An
                                # area-only estimate is unsafe for very thin/long pages.
                                while render_dpi >= 10 and (
                                    math.ceil(page.rect.width * render_dpi / 72)
                                    * math.ceil(page.rect.height * render_dpi / 72)
                                    > MAX_PIXELS
                                ):
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
                        "Target size cannot be met. Increase the limit or select rasterized mode.",
                    )
                return output.publish([name], cancel_token)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConversionError(ErrorCode.OUTPUT_ERROR, f"Compression failed: {exc}") from exc
