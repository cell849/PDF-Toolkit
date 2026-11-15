"""Optional offline FFmpeg reconstruction of primary audio/video streams.

No stream is copied. Reports contain category counts, never source tag values or
source filenames. Audible/visible information is outside this metadata policy.
"""

import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from local_pdf_toolkit.converters.office_pdf import _run
from local_pdf_toolkit.core.contracts import (
    CancellationToken,
    ConverterSpec,
    OptionDefinition,
    Progress,
)
from local_pdf_toolkit.core.errors import ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat
from local_pdf_toolkit.core.output import OutputTransaction

MAX_BYTES = 512 * 1024 * 1024
MAX_OUTPUT_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_DURATION = 3600
MAX_PROBE_BYTES = 16 * 1024 * 1024
DEMUXERS = "mov,matroska,webm,avi,mp3,wav,flac,ogg,aac"
_FORMATS = ("mp4", "mov", "mkv", "webm", "avi", "mp3", "m4a", "wav", "flac", "ogg", "aac")
_ENTRIES = (
    "format=format_name,duration:format_tags:"
    "stream=index,codec_type,codec_name,width,height,duration,avg_frame_rate,channels,sample_rate:"
    "stream_tags:stream_disposition:stream_side_data=side_data_type:chapter=id:chapter_tags"
)


def find_ffmpeg():
    """Find separately installed local binaries; never download executables."""
    for name in ("ffmpeg", "ffmpeg.exe"):
        if binary := shutil.which(name):
            path = Path(binary)
            probe = path.with_name("ffprobe.exe" if path.suffix.lower() == ".exe" else "ffprobe")
            if probe.is_file():
                return path, probe
            if found := shutil.which("ffprobe") or shutil.which("ffprobe.exe"):
                return path, Path(found)
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "LOCALAPPDATA"):
            if base := os.environ.get(variable):
                for subdirectory in (Path("FFmpeg/bin"), Path("ffmpeg/bin")):
                    directory = Path(base) / subdirectory
                    binary, probe = directory / "ffmpeg.exe", directory / "ffprobe.exe"
                    if binary.is_file() and probe.is_file():
                        return binary, probe
    return None


def _invalid(message):
    raise ConversionError(ErrorCode.INVALID_INPUT, message)


def _binaries():
    found = find_ffmpeg()
    if found is None:
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED,
            "FFmpeg and ffprobe are not installed. Install both locally to use this tool.",
        )
    return found


def _execute(command, timeout, cancel_token):
    cancel_token.raise_if_cancelled()
    try:
        # The shared runner bounds time and terminates the process tree on cancel.
        _run(command, timeout, cancel_token)
    except ConversionError as exc:
        if exc.code == ErrorCode.CANCELLED:
            raise
        message = (
            "Media processing timed out."
            if "timed out" in str(exc)
            else ("Cannot decode or encode this media with the installed FFmpeg.")
        )
        raise ConversionError(ErrorCode.CONVERSION_FAILED, message) from exc
    except OSError as exc:
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED, "Cannot run the installed FFmpeg tools."
        ) from exc


def _check_file(path):
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
            _invalid("Choose a regular media file no larger than 512 MiB.")
    except OSError as exc:
        raise ConversionError(ErrorCode.INVALID_INPUT, "Cannot read the source media.") from exc


def _snapshot(path, destination, token):
    """Bound the actual bytes passed to FFmpeg, including a changing source."""
    _check_file(path)
    size = 0
    try:
        with path.open("rb") as source, destination.open("xb") as target:
            while data := source.read(1024 * 1024):
                token.raise_if_cancelled()
                size += len(data)
                if size > MAX_BYTES:
                    _invalid("Source media exceeds the 512 MiB limit.")
                target.write(data)
        if not size:
            _invalid("Source media is empty.")
    except OSError as exc:
        raise ConversionError(
            ErrorCode.INVALID_INPUT, "Cannot read or stage the source media."
        ) from exc


def _probe(path, binary, directory, timeout, token, *, output=False):
    metadata = directory / ("output-probe.json" if output else "source-probe.json")
    command = [
        str(binary),
        "-v",
        "error",
        "-max_alloc",
        str(64 * 1024 * 1024),
        "-protocol_whitelist",
        "file,pipe",
        "-format_whitelist",
        DEMUXERS,
        "-show_entries",
        _ENTRIES,
        "-of",
        "json",
        "-o",
        str(metadata),
        str(path.resolve()),
    ]
    try:
        _execute(command, timeout, token)
        if not metadata.is_file() or metadata.stat().st_size > MAX_PROBE_BYTES:
            raise ValueError("Oversized or missing media description")
        result = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("streams"), list):
            raise ValueError("Invalid media description")
        return result
    except ConversionError as exc:
        if output or exc.code == ErrorCode.CANCELLED or "timed out" in str(exc):
            raise
        raise ConversionError(
            ErrorCode.INVALID_INPUT, "Cannot parse this supported media file."
        ) from exc
    except (OSError, ValueError, TypeError) as exc:
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED if output else ErrorCode.INVALID_INPUT,
            "Cannot verify the media description.",
        ) from exc


def _primary(streams, kind):
    candidates = [
        stream
        for stream in streams
        if stream.get("codec_type") == kind
        and not stream.get("disposition", {}).get("attached_pic")
    ]
    return next(
        (s for s in candidates if s.get("disposition", {}).get("default")),
        candidates[0] if candidates else None,
    )


def _inspect(info):
    """Accept supported demuxers and bounded primary streams, independently of suffix."""
    streams = info["streams"]
    if not streams or len(streams) > 128 or any(not isinstance(s, dict) for s in streams):
        _invalid("Media must have between one and 128 streams.")
    video, audio = _primary(streams, "video"), _primary(streams, "audio")
    if video is None and audio is None:
        _invalid("Media has no playable primary audio or video stream.")
    for stream in streams:
        if type(stream.get("index")) is not int or stream["index"] < 0:
            _invalid("Invalid media stream index.")
    if video is not None:
        width, height = video.get("width"), video.get("height")
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            _invalid("Invalid video dimensions.")
        if ((width + 1) // 2 * 2) * ((height + 1) // 2 * 2) > MAX_PIXELS:
            _invalid("Video exceeds the 40-million-pixel limit.")
    if audio is not None:
        try:
            channels, sample_rate = audio["channels"], int(audio["sample_rate"])
            if (
                type(channels) is not int
                or not 1 <= channels <= 8
                or not 1 <= sample_rate <= 192000
            ):
                raise ValueError("Audio limits")
        except (KeyError, TypeError, ValueError) as exc:
            raise ConversionError(
                ErrorCode.INVALID_INPUT, "Audio is limited to eight channels and 192 kHz."
            ) from exc
    try:
        durations = [float(info.get("format", {}).get("duration", "nan"))]
        durations.extend(float(s["duration"]) for s in (video, audio) if s and "duration" in s)
        durations = [value for value in durations if math.isfinite(value)]
        retained_duration = _duration(info, [s for s in (video, audio) if s is not None])
        if (
            not durations
            or min(durations) <= 0
            or max(durations) > MAX_DURATION
            or not math.isfinite(retained_duration)
            or not 0 < retained_duration <= MAX_DURATION
        ):
            raise ValueError("Duration limits")
    except (KeyError, TypeError, ValueError) as exc:
        raise ConversionError(
            ErrorCode.INVALID_INPUT,
            "Media needs a known positive duration no longer than one hour.",
        ) from exc
    demuxer = info.get("format", {}).get("format_name")
    if demuxer == "mov,mp4,m4a,3gp,3g2,mj2":
        brand = info["format"].get("tags", {}).get("major_brand", "").strip()
        kind = "mov" if brand == "qt" else "mp4" if video is not None else "m4a"
    elif demuxer == "matroska,webm":
        # ffprobe exposes Matroska and its WebM subset as one demuxer.
        kind = "mkv"
    elif demuxer in ("avi", "mp3", "wav", "flac", "ogg", "aac"):
        kind = demuxer
    else:
        raise ConversionError(ErrorCode.UNSUPPORTED_FORMAT, "Unsupported media container.")
    return FileFormat(kind), video, audio


def _counts(info, video, audio):
    streams, chapters = info["streams"], info.get("chapters", [])
    return {
        "metadata_tags": len(info.get("format", {}).get("tags", {}))
        + sum(len(s.get("tags", {})) for s in streams)
        + sum(len(c.get("tags", {})) for c in chapters),
        "chapters": len(chapters),
        "subtitles": sum(s.get("codec_type") == "subtitle" for s in streams),
        "attachments_and_cover_art": sum(
            s.get("codec_type") == "attachment"
            or bool(s.get("disposition", {}).get("attached_pic"))
            for s in streams
        ),
        "other_audio_tracks": sum(s.get("codec_type") == "audio" for s in streams)
        - (audio is not None),
        "other_video_tracks": sum(
            s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
            for s in streams
        )
        - (video is not None),
        "data_and_other_tracks": sum(
            s.get("codec_type") not in ("video", "audio", "subtitle", "attachment") for s in streams
        ),
        "stream_side_data": sum(len(s.get("side_data_list", [])) for s in streams),
    }


def _duration(info, streams):
    """Prefer retained-track lengths; Matroska stores those in DURATION tags."""
    durations = []
    for stream in streams:
        try:
            if "duration" in stream:
                value = float(stream["duration"])
            else:
                tags = stream.get("tags", {})
                text = next(value for key, value in tags.items() if key.upper() == "DURATION")
                hours, minutes, seconds = text.split(":")
                value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Invalid duration")
            durations.append(value)
        except (StopIteration, TypeError, ValueError):
            break
    if len(durations) == len(streams):
        return max(durations)
    return float(info["format"]["duration"])


def _verify_duration(source, cleaned, video, audio):
    selected = [s for s in (video, audio) if s is not None]
    expected = _duration(source, selected)
    actual = _duration(cleaned, cleaned["streams"])
    tolerance = 0.25  # AAC/FLAC packet rounding and container time bases.
    if video is not None:
        try:
            numerator, denominator = video.get("avg_frame_rate", "0/0").split("/")
            frame_length = float(denominator) / float(numerator)
            if math.isfinite(frame_length) and frame_length > 0:
                tolerance = max(tolerance, min(frame_length, 2))
        except (TypeError, ValueError, ZeroDivisionError):
            pass
    if abs(actual - expected) > tolerance:
        raise ConversionError(
            ErrorCode.CONVERSION_FAILED,
            "Cleaned media duration differs; no partial recording was saved.",
        )


def _verify(info, has_video, has_audio):
    """Reject extra output tracks, chapters, arbitrary tags and stream side data."""
    streams = info.get("streams", [])
    expected = (["video"] if has_video else []) + (["audio"] if has_audio else [])
    if info.get("chapters") or [s.get("codec_type") for s in streams] != expected:
        raise ConversionError(ErrorCode.CONVERSION_FAILED, "Unexpected tracks in cleaned media.")
    allowed_format = (
        {
            "major_brand": {"isom"},
            "minor_version": {"512"},
            "compatible_brands": {"isomiso2avc1mp41"},
        }
        if has_video
        else {}
    )
    for key, value in info.get("format", {}).get("tags", {}).items():
        if value not in allowed_format.get(key, set()):
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "Unexpected output container metadata."
            )
    for stream in streams:
        kind = stream["codec_type"]
        codec = "h264" if kind == "video" else "aac" if has_video else "flac"
        if stream.get("codec_name") != codec or stream.get("side_data_list"):
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, "Unexpected output codec or side data."
            )
        allowed = (
            {
                "language": {"und"},
                "handler_name": {"VideoHandler", "SoundHandler"},
                "vendor_id": {"[0][0][0][0]"},
                "encoder": {"Lavc libx264"} if kind == "video" else set(),
            }
            if has_video
            else {}
        )
        for key, value in stream.get("tags", {}).items():
            if value not in allowed.get(key, set()):
                raise ConversionError(
                    ErrorCode.CONVERSION_FAILED, "Unexpected output stream metadata."
                )
        if any(value for key, value in stream.get("disposition", {}).items() if key != "default"):
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "Unexpected output track flags.")
    _inspect(info)


def inspect_media(path, token):
    """Return a validated container and category counts, without source tag values."""
    token.raise_if_cancelled()
    path = Path(path)
    _check_file(path)
    _, probe = _binaries()
    with tempfile.TemporaryDirectory(prefix="pdf-toolkit-media-") as temporary:
        directory = Path(temporary)
        source = directory / "source.media"
        _snapshot(path, source, token)
        info = _probe(source, probe, directory, 120, token)
        kind, video, audio = _inspect(info)
        token.raise_if_cancelled()
        return {"format": kind, "counts": _counts(info, video, audio)}


class MediaMetadataConverter:
    def __init__(self):
        self.spec = ConverterSpec(
            "metadata.clean_media",
            "Clean audio / video metadata (FFmpeg)",
            tuple(FileFormat(kind) for kind in _FORMATS),
            (FileFormat.MP4, FileFormat.FLAC),
            (
                OptionDefinition(
                    "timeout",
                    "Timeout per process (seconds)",
                    120,
                    "Maximum time for each local FFmpeg/ffprobe process.",
                    minimum=5,
                    maximum=600,
                ),
            ),
            (
                "Requires separately installed FFmpeg and ffprobe. Re-encodes primary video/audio "
                "to MP4 (H.264/AAC), or primary audio to FLAC. No stream is copied.",
                "Drops chapters, subtitles, attachments, cover art, other tracks and source tags. "
                "Video is normalized to 8-bit YUV420p; odd dimensions are padded. Audio-only "
                "FLAC uses 24-bit samples. Quality, color and timing may change.",
                "One-hour, 512 MiB input/output and 40-million-pixel limits; "
                "up to eight audio channels/192 kHz. "
                "Visible/audible personal information remains. This is not an anonymity guarantee.",
            ),
        )

    def validate_options(self, options):
        timeout = options.get("timeout", 120)
        if set(options) - {"timeout"} or type(timeout) is not int or not 5 <= timeout <= 600:
            raise ConversionError(ErrorCode.INVALID_OPTIONS, "Timeout must be 5–600 seconds.")
        return {"timeout": timeout}

    def validate_input(self, input_path):
        return inspect_media(input_path, CancellationToken())["format"]

    def convert(self, input_path, output_dir, options, progress, cancel_token):
        options = self.validate_options(options)
        cancel_token.raise_if_cancelled()
        binary, probe = _binaries()
        try:
            with (
                tempfile.TemporaryDirectory(prefix="pdf-toolkit-media-") as temporary,
                OutputTransaction(Path(output_dir)) as outputs,
            ):
                directory = Path(temporary)
                source = directory / "source.media"
                _snapshot(Path(input_path), source, cancel_token)
                progress(Progress())
                info = _probe(source, probe, directory, options["timeout"], cancel_token)
                kind, video, audio = _inspect(info)
                name = f"clean-media-{uuid4().hex[:12]}.{'mp4' if video else 'flac'}"
                command = [
                    str(binary),
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-xerror",
                    "-n",
                    "-max_alloc",
                    str(256 * 1024 * 1024),
                    "-threads",
                    "2",
                    "-filter_threads",
                    "1",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-format_whitelist",
                    DEMUXERS,
                    "-err_detect",
                    "explode",
                    "-i",
                    str(source),
                ]
                for stream in (video, audio):
                    if stream is not None:
                        command.extend(["-map", f"0:{stream['index']}"])
                command.extend(
                    [
                        "-map_metadata",
                        "-1",
                        "-map_metadata:s",
                        "-1",
                        "-map_chapters",
                        "-1",
                        "-sn",
                        "-dn",
                        "-fflags",
                        "+bitexact",
                        "-flags",
                        "+bitexact",
                        "-metadata",
                        "encoder=",
                        "-metadata:s",
                        "encoder=",
                        "-threads",
                        "2",
                        "-fs",
                        str(MAX_OUTPUT_BYTES),
                    ]
                )
                if video is not None:
                    command.extend(
                        [
                            "-c:v",
                            "libx264",
                            "-preset",
                            "medium",
                            "-crf",
                            "20",
                            "-vf",
                            "sidedata=delete,pad=ceil(iw/2)*2:ceil(ih/2)*2",
                            "-pix_fmt",
                            "yuv420p",
                            "-a53cc",
                            "0",
                            "-bsf:v",
                            "filter_units=remove_types=6",
                            "-metadata:s:v",
                            "rotate=",
                            "-disposition:v:0",
                            "default",
                            "-movflags",
                            "+faststart",
                            "-f",
                            "mp4",
                        ]
                    )
                    if audio is not None:
                        command.extend(["-c:a", "aac", "-b:a", "192k"])
                else:
                    command.extend(["-vn", "-c:a", "flac", "-sample_fmt", "s32", "-f", "flac"])
                if audio is not None:
                    command.extend(["-af", "asidedata=delete", "-disposition:a:0", "default"])
                produced = outputs.staging / name
                command.append(str(produced))
                _execute(command, options["timeout"], cancel_token)
                if not produced.is_file() or not produced.stat().st_size:
                    raise ConversionError(
                        ErrorCode.CONVERSION_FAILED, "FFmpeg produced no cleaned media."
                    )
                # FFmpeg -fs may stop successfully and overshoot by one packet.
                # Reject the cap's neighbourhood as well as any short recording.
                margin = min(1024 * 1024, MAX_OUTPUT_BYTES // 10)
                if produced.stat().st_size >= MAX_OUTPUT_BYTES - margin:
                    raise ConversionError(
                        ErrorCode.CONVERSION_FAILED,
                        "Cleaned media reached the 512 MiB output limit; "
                        "no partial recording was saved.",
                    )
                cleaned = _probe(
                    produced, probe, directory, options["timeout"], cancel_token, output=True
                )
                _verify(cleaned, video is not None, audio is not None)
                _verify_duration(info, cleaned, video, audio)
                report = {
                    "tool": "metadata.clean_media",
                    "source_container": kind.value,
                    "output_container": "mp4" if video else "flac",
                    "removed_category_counts": _counts(info, video, audio),
                    "policy_categories": [
                        "source tags",
                        "chapters",
                        "subtitles",
                        "attachments",
                        "cover art",
                        "other tracks",
                        "frame side data",
                    ],
                    "policy": "Fresh primary-stream transcode; "
                    "no source metadata or stream copying.",
                    "limits": "Necessary generated container/codec structure remains. Audible and "
                    "visible personal information is not anonymized; encoding may change quality.",
                }
                report_name = Path(name).stem + ".report.json"
                (outputs.staging / report_name).write_text(
                    json.dumps(report, indent=2) + "\n", encoding="utf-8"
                )
                cancel_token.raise_if_cancelled()
                paths = outputs.publish([name, report_name], cancel_token)
            progress(Progress(1, 1))
            return paths
        except OSError as exc:
            raise ConversionError(
                ErrorCode.OUTPUT_ERROR,
                "Cannot write cleaned media; check collisions and permissions.",
            ) from exc


def media_metadata_converters():
    return (MediaMetadataConverter(),)
