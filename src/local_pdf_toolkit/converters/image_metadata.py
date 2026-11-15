"""Rebuild supported single-frame images from pixels, never copying source metadata.

This does not anonymize depicted people, visible writing or pixel steganography.
JPEG is re-encoded at quality 95; some color modes normalize without ICC.
"""

import io
import json
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from local_pdf_toolkit.converters.images import FORMATS
from local_pdf_toolkit.core.contracts import ConverterSpec, Progress
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.output import OutputTransaction

MAX_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 40_000_000
EXTENSIONS = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "TIFF": "tiff",
    "BMP": "bmp",
    "GIF": "gif",
}


def _invalid(message):
    raise ConversionError(ErrorCode.INVALID_INPUT, message)


def _open(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        _invalid("Choose a nonempty supported image no larger than 512 MiB.")
    image = Image.open(io.BytesIO(data))
    try:
        if image.format not in FORMATS:
            raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, "Unsupported image container.")
        if image.width * image.height > MAX_PIXELS:
            _invalid("Image exceeds the 40-million-pixel limit.")
        if getattr(image, "n_frames", 1) != 1:
            _invalid("Animated and multi-page images are unsupported; no frames were removed.")
        image.load()
        return image
    except Exception:
        image.close()
        raise


def verify_clean_image_bytes(data, expected=None):
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if (expected is not None and image.format != expected) or (
            image.format != "TIFF" and image.getexif()
        ):
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "Cleaned image verification failed.")
        forbidden = {"exif", "xmp", "icc_profile", "comment", "XML:com.adobe.xmp", "description"}
        if forbidden.intersection(image.info):
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "Image still contains metadata.")
        if image.format == "TIFF":
            structural = {256, 257, 258, 259, 262, 273, 277, 278, 279, 284, 338, 339}
            # TIFF exposes its structural IFD through getexif too; verified separately below.
            if set(image.tag_v2) - structural:
                raise ConversionError(ErrorCode.CONVERSION_FAILED, "Unexpected TIFF tags remain.")


def clean_image_bytes(data: bytes) -> bytes:
    """Return a same-container image reconstructed from oriented pixels only.

    The output retains necessary format structure, not EXIF/GPS/IPTC/XMP/ICC,
    comments, source thumbnails or appended data. It intentionally normalizes
    some color modes and may change ICC-managed appearance.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with _open(data) as source:
                kind = source.format
                with ImageOps.exif_transpose(source) as oriented:
                    alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                    mode = "RGBA" if alpha and kind in ("PNG", "WEBP", "TIFF", "GIF") else "RGB"
                    if kind in ("PNG", "TIFF") and oriented.mode in (
                        "I;16",
                        "I;16B",
                        "I;16L",
                        "I",
                        "F",
                    ):
                        mode = oriented.mode
                    with oriented.convert(mode) as converted:
                        # A fresh instance severs info, EXIF and TIFF tag dictionaries.
                        with Image.frombytes(mode, converted.size, converted.tobytes()) as fresh:
                            result = io.BytesIO()
                            options = {"quality": 95} if kind == "JPEG" else {}
                            if kind == "WEBP":
                                options["lossless"] = True
                            if kind == "TIFF":
                                options["compression"] = "tiff_deflate"
                            fresh.save(result, format=kind, **options)
                            cleaned = result.getvalue()
            verify_clean_image_bytes(cleaned, kind)
            return cleaned
    except ConversionError:
        raise
    except (
        OSError,
        ValueError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ConversionError(
            ErrorCode.INVALID_INPUT, "Cannot decode or clean this image."
        ) from exc


class ImageMetadataConverter:
    spec = ConverterSpec(
        "metadata.clean_image",
        "Clean image metadata",
        tuple(FORMATS.values()),
        tuple(FORMATS.values()),
        limitations=(
            "Rebuilds a single-frame image without EXIF/GPS, XMP/IPTC, ICC, "
            "comments or thumbnails. "
            "Output uses a neutral filename. Necessary container structure remains.",
            "JPEG is re-encoded at quality 95. Some modes convert to RGB/RGBA; "
            "removing color profiles can change appearance. Visible personal information and "
            "pixel steganography remain. This is not an anonymity guarantee.",
        ),
    )

    def validate_options(self, options):
        if options:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "This tool has no conversion options.")
        return {}

    @staticmethod
    def _read(path):
        path = Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
            _invalid("Choose a regular image no larger than 512 MiB.")
        try:
            with path.open("rb") as source:
                data = source.read(MAX_BYTES + 1)
        except OSError as exc:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Cannot read the source image.") from exc
        if len(data) > MAX_BYTES:
            _invalid("Input exceeds 512 MiB.")
        return data

    def validate_input(self, input_path):
        try:
            with _open(self._read(input_path)) as image:
                return FORMATS[image.format]
        except ConversionError:
            raise
        except (OSError, ValueError, SyntaxError) as exc:
            raise ConversionError(ErrorCode.INVALID_INPUT, "Cannot read this image.") from exc

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        self.validate_options(options)
        cancel_token.raise_if_cancelled()
        try:
            data = self._read(input_path)
            progress(Progress(0, 1))
            cancel_token.raise_if_cancelled()
            cleaned = clean_image_bytes(data)
            cancel_token.raise_if_cancelled()
            with Image.open(io.BytesIO(cleaned)) as image:
                name = f"clean-image-{uuid4().hex[:12]}.{EXTENSIONS[image.format]}"
                report = {
                    "tool": "metadata.clean_image",
                    "format": image.format,
                    "width": image.width,
                    "height": image.height,
                    "policy": "Rebuilt from oriented pixels; source metadata and trailers omitted.",
                    "policy_categories": ["EXIF/GPS", "XMP/IPTC", "ICC", "comments", "thumbnails"],
                    "encoding": "Pixels rebuilt; JPEG quality 95; WebP lossless; "
                    "color modes may convert.",
                    "limits": "Visible content, pixel steganography and filesystem data "
                    "are not anonymized. "
                    "ICC removal can change color; JPEG is re-encoded.",
                }
                report_name = Path(name).stem + ".report.json"
            with OutputTransaction(Path(output_dir)) as output:
                (output.staging / name).write_bytes(cleaned)
                cancel_token.raise_if_cancelled()
                (output.staging / report_name).write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                paths = output.publish([name, report_name], cancel_token)
            progress(Progress(1, 1))
            return paths
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "Cannot write cleaned image; check collisions and permissions.",
            ) from exc
