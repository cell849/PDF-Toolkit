"""Verified image conversion, ordered image PDFs, and bounded size targeting."""

import io
import re
import warnings
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps, UnidentifiedImageError, features

from local_pdf_toolkit.core.contracts import ConverterSpec, OptionDefinition, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

FORMATS = {
    "JPEG": FileFormat.JPEG,
    "PNG": FileFormat.PNG,
    "WEBP": FileFormat.WEBP,
    "TIFF": FileFormat.TIFF,
    "BMP": FileFormat.BMP,
    "GIF": FileFormat.GIF,
}
if features.check("avif"):
    FORMATS["AVIF"] = FileFormat.AVIF
try:
    import pillow_heif
except ImportError:
    pass
else:
    pillow_heif.register_heif_opener()
    FORMATS["HEIF"] = FileFormat.HEIC

Image.MAX_IMAGE_PIXELS = 40_000_000


def safe_stem(path):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(path).stem).rstrip(" .")[:100] or "document"


def open_image(path):
    try:
        path = Path(path)
        if not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Choose an image below 512 MiB.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in FORMATS or image.width * image.height > 40_000_000:
                    raise ConversionError(
                        ErrorCode.INVALID_INPUT, "Unsupported or oversized image."
                    )
                if getattr(image, "n_frames", 1) != 1:
                    raise ConversionError(
                        ErrorCode.INVALID_INPUT,
                        "Multi-frame images are unsupported; extract frames first.",
                    )
                image.load()
                # exif_transpose already returns an independent image.
                result = ImageOps.exif_transpose(image)
                result.format = image.format
                return result
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ConversionError(ErrorCode.INVALID_INPUT, f"Cannot read image: {exc}") from exc


def opaque(image):
    if "A" not in image.getbands() and "transparency" not in image.info:
        # Still return an owned copy; the caller closes the original image.
        return image.convert("RGB")
    with image.convert("RGBA") as rgba, rgba.getchannel("A") as alpha:
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=alpha)
        return background


class ImageConverter:
    def __init__(self, output_format):
        self.format = output_format
        options = (
            OptionDefinition(
                "width",
                "Maximum width (px, 0 = original)",
                0,
                "Keep aspect ratio.",
                minimum=0,
                maximum=20000,
            ),
            OptionDefinition(
                "height",
                "Maximum height (px, 0 = original)",
                0,
                "Keep aspect ratio.",
                minimum=0,
                maximum=20000,
            ),
            OptionDefinition(
                "target_kib",
                "Maximum file size (KiB, 0 = no target)",
                0,
                "A KiB is 1024 bytes. May reduce quality and resolution.",
                minimum=0,
                maximum=1000000,
            ),
        )
        if output_format in (FileFormat.JPEG, FileFormat.WEBP):
            options += (
                OptionDefinition(
                    "quality", "Maximum quality", 85, "1–100.", minimum=1, maximum=100
                ),
            )
        self.spec = ConverterSpec(
            f"image.to_{output_format.value}",
            f"Image to {output_format.value.upper()} / resize / compress",
            tuple(FORMATS.values()),
            (output_format,),
            options,
            (
                "Preserves aspect ratio. Metadata is removed. "
                "Animated/multi-frame images are rejected. Size targeting may resize.",
            ),
        )

    def validate_input(self, path):
        with open_image(path) as image:
            return FORMATS[image.format]

    def validate_options(self, options):
        definitions = {d.name: d for d in self.spec.options}
        if set(options) - definitions.keys():
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Unknown image option.")
        result = {}
        for name, definition in definitions.items():
            value = options.get(name, definition.default)
            if type(value) is not int or not definition.minimum <= value <= definition.maximum:
                raise ConversionError(ErrorCode.INVALID_OPTIONS, f"Invalid {definition.label}.")
            result[name] = value
        return result

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        opts = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        image = open_image(input_path)
        try:
            image.thumbnail(
                (opts["width"] or image.width, opts["height"] or image.height),
                Image.Resampling.LANCZOS,
            )
            target = opts["target_kib"] * 1024
            file_format = self.format.value.upper()
            if self.format in (FileFormat.JPEG, FileFormat.BMP):
                converted = opaque(image)
                image.close()
                image = converted
            elif self.format == FileFormat.WEBP or (
                self.format == FileFormat.PNG and image.mode in ("CMYK", "F")
            ):
                mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                converted = image.convert(mode)
                image.close()
                image = converted
            # Preserve palette transparency while dropping descriptive metadata.
            transparency = image.info.get("transparency")
            image.info.clear()
            if transparency is not None:
                image.info["transparency"] = transparency
            result = None
            for attempt in range(32):
                cancel_token.raise_if_cancelled()
                qualities = (
                    list(range(opts.get("quality", 85), 0, -5))
                    if "quality" in opts and target
                    else [opts.get("quality", 85)]
                )
                for quality in qualities:
                    cancel_token.raise_if_cancelled()
                    buffer = io.BytesIO()
                    kwargs = {"quality": quality} if "quality" in opts else {"optimize": True}
                    image.save(buffer, format=file_format, **kwargs)
                    data = buffer.getvalue()
                    if not target or len(data) <= target:
                        result = data
                        break
                progress(Progress(attempt + 1, 32))
                if result is not None:
                    break
                size = (max(1, int(image.width * 0.8)), max(1, int(image.height * 0.8)))
                if size == image.size:
                    break
                resized = image.resize(size, Image.Resampling.LANCZOS)
                image.close()
                image = resized
            if result is None:
                raise ConversionError(
                    ErrorCode.INVALID_OPTIONS, "Target size cannot be met. Increase the size limit."
                )
            extension = "jpg" if self.format == FileFormat.JPEG else self.format.value
            name = f"{safe_stem(input_path)}_converted.{extension}"
            with OutputTransaction(Path(output_dir)) as output:
                (output.staging / name).write_bytes(result)
                paths = output.publish([name], cancel_token)
            progress(Progress(32, 32))
            return paths
        except OSError as exc:
            raise ConversionError(ErrorCode.OUTPUT_ERROR, f"Cannot save image: {exc}") from exc
        finally:
            image.close()


class ImagesPdfConverter:
    spec = ConverterSpec(
        "image.to_pdf",
        "Images to PDF (ordered files)",
        tuple(FORMATS.values()),
        (FileFormat.PDF,),
        (
            OptionDefinition(
                "page_size",
                "Page size",
                "image",
                "Image uses 96 pixels per inch.",
                ("image", "A4", "Letter"),
            ),
        ),
        ("One image per page, in file-list order. Transparent areas become white.",),
        input_mode="multiple",
    )

    def validate_input(self, path):
        return ImageConverter(FileFormat.PNG).validate_input(path)

    def validate_options(self, options):
        value = options.get("page_size", "image")
        if set(options) - {"page_size"} or value not in ("image", "A4", "Letter"):
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Invalid page sizing.")
        return {"page_size": value}

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        opts = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        paths = (Path(input_path),) if isinstance(input_path, str | Path) else tuple(input_path)
        if not paths or len(paths) > 10000:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Select 1–10,000 images.")
        try:
            with OutputTransaction(Path(output_dir)) as output, pymupdf.open() as document:
                for index, path in enumerate(paths, 1):
                    cancel_token.raise_if_cancelled()
                    with open_image(path) as source, opaque(source) as image:
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                        size = {"A4": (595, 842), "Letter": (612, 792)}.get(
                            opts["page_size"], (image.width * 0.75, image.height * 0.75)
                        )
                        page = document.new_page(width=size[0], height=size[1])
                        page.insert_image(page.rect, stream=buffer.getvalue(), keep_proportion=True)
                    progress(Progress(index, len(paths)))
                name = f"{safe_stem(paths[0])}_images.pdf"
                document.save(output.staging / name, garbage=4, deflate=True)
                return output.publish([name], cancel_token)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ConversionError(ErrorCode.OUTPUT_ERROR, f"Cannot create PDF: {exc}") from exc


def image_converters():
    return [
        ImagesPdfConverter(),
        *(
            ImageConverter(f)
            for f in (
                FileFormat.JPEG,
                FileFormat.PNG,
                FileFormat.WEBP,
                FileFormat.TIFF,
                FileFormat.BMP,
            )
        ),
    ]
