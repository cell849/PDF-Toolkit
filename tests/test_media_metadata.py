"""Synthetic media only; real FFmpeg tests skip when local binaries are absent."""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from PIL import Image

from local_pdf_toolkit.converters import media_metadata as media
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


@pytest.fixture
def binaries():
    found = media.find_ffmpeg()
    if found is None:
        pytest.skip("Separately installed FFmpeg/ffprobe are unavailable")
    return found


def generate(binary, arguments, destination):
    command = [str(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    subprocess.run(
        command + arguments + [str(destination)], check=True, capture_output=True, timeout=30
    )
    return destination


@pytest.fixture
def audio_source(tmp_path, binaries):
    cover = tmp_path / "private-cover.png"
    Image.new("RGB", (16, 16), "red").save(cover)
    return generate(
        binaries[0],
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-i",
            str(cover),
            "-map",
            "0:a",
            "-map",
            "1:v",
            "-c:a",
            "libmp3lame",
            "-c:v",
            "png",
            "-disposition:v",
            "attached_pic",
            "-metadata",
            "artist=Private Owner",
            "-metadata",
            "comment=Private Location",
            "-metadata:s:v",
            "title=Private Cover",
        ],
        tmp_path / "Private Owner's audio.mp3",
    )


@pytest.fixture
def video_source(tmp_path, binaries):
    subtitles = tmp_path / "private-subtitles.srt"
    subtitles.write_text("1\n00:00:00,000 --> 00:00:00,400\nPrivate subtitle\n", encoding="utf-8")
    attachment = tmp_path / "private-attachment.txt"
    attachment.write_text("Private attached contents", encoding="utf-8")
    chapters = tmp_path / "private-chapters.txt"
    chapters.write_text(
        ";FFMETADATA1\ntitle=Private Owner\n[CHAPTER]\nTIMEBASE=1/1000\n"
        "START=0\nEND=400\ntitle=Private Chapter\n",
        encoding="utf-8",
    )
    return generate(
        binaries[0],
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x24:r=4:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=32x24:r=4:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=880:duration=0.5",
            "-i",
            str(subtitles),
            "-f",
            "ffmetadata",
            "-i",
            str(chapters),
            "-map",
            "0:v",
            "-map",
            "1:v",
            "-map",
            "2:a",
            "-map",
            "3:a",
            "-map",
            "4:s",
            "-map_metadata",
            "5",
            "-map_chapters",
            "5",
            "-c:v",
            "ffv1",
            "-c:a",
            "pcm_s16le",
            "-c:s",
            "srt",
            "-disposition:v:0",
            "default",
            "-disposition:v:1",
            "0",
            "-disposition:a:0",
            "default",
            "-metadata:s:a:0",
            "language=fra",
            "-metadata:s:v:0",
            "title=Private Video",
            "-attach",
            str(attachment),
            "-metadata:s:t",
            "mimetype=text/plain",
        ],
        tmp_path / "Private Owner's video.mkv",
    )


def probe(path, binaries, tmp_path):
    return media._probe(path, binaries[1], tmp_path, 10, CancellationToken())


def test_audio_reencoded_without_tags_or_cover_art_and_source_unchanged(
    tmp_path,
    binaries,
    audio_source,
):
    converter = media.MediaMetadataConverter()
    original = audio_source.read_bytes()
    assert converter.validate_input(audio_source) == FileFormat.MP3
    before = probe(audio_source, binaries, tmp_path)
    assert before["format"]["tags"]["artist"] == "Private Owner"
    assert len(before["streams"]) == 2
    updates = []
    paths = converter.convert(audio_source, tmp_path, {}, updates.append, CancellationToken())
    assert paths[0].suffix == ".flac"
    assert paths[0].name.startswith("clean-media-")
    after = probe(paths[0], binaries, tmp_path)
    assert [stream["codec_name"] for stream in after["streams"]] == ["flac"]
    assert not after["format"].get("tags")
    assert not after["streams"][0].get("tags")
    report = json.loads(paths[1].read_text())
    assert report["removed_category_counts"]["attachments_and_cover_art"] == 1
    assert report["removed_category_counts"]["metadata_tags"] >= 3
    assert all("Private" not in path.name for path in paths)
    assert "Private" not in paths[1].read_text()
    assert audio_source.read_bytes() == original
    assert updates[-1].completed == updates[-1].total == 1
    assert not list(tmp_path.glob(".pdf-toolkit-*"))
    other = converter.convert(audio_source, tmp_path, {}, lambda _: None, CancellationToken())
    assert other[0] != paths[0]


def test_video_primary_tracks_only_chapters_subtitles_attachments_dropped(
    tmp_path,
    binaries,
    video_source,
):
    converter = media.MediaMetadataConverter()
    assert converter.validate_input(video_source) == FileFormat.MKV
    inventory = media.inspect_media(video_source, CancellationToken())
    assert inventory["format"] == FileFormat.MKV
    assert inventory["counts"]["chapters"] == 1
    assert all(type(value) is int for value in inventory["counts"].values())
    assert "Private" not in json.dumps(inventory)
    original = video_source.read_bytes()
    paths = converter.convert(video_source, tmp_path, {}, lambda _: None, CancellationToken())
    assert paths[0].suffix == ".mp4"
    after = probe(paths[0], binaries, tmp_path)
    assert [s["codec_name"] for s in after["streams"]] == ["h264", "aac"]
    assert not after.get("chapters")
    assert not any(s.get("side_data_list") for s in after["streams"])
    assert "Private" not in json.dumps(after)
    counts = json.loads(paths[1].read_text())["removed_category_counts"]
    assert counts["subtitles"] == counts["chapters"] == 1
    assert counts["attachments_and_cover_art"] == 1
    assert counts["other_audio_tracks"] == counts["other_video_tracks"] == 1
    assert "Private" not in paths[1].read_text()
    assert video_source.read_bytes() == original
    # Decode a real output frame to show that the selected primary (red) video survived.
    decoded = subprocess.run(
        [
            str(binaries[0]),
            "-v",
            "error",
            "-i",
            str(paths[0]),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    ).stdout
    assert len(decoded) == 32 * 24 * 3
    assert decoded[0] > 200 and decoded[1] < 20 and decoded[2] < 20


@pytest.mark.parametrize(
    "container,codec",
    [
        ("wav", "pcm_s16le"),
        ("flac", "flac"),
        ("ogg", "libvorbis"),
        ("aac", "aac"),
    ],
)
def test_other_audio_containers_and_content_validation(tmp_path, binaries, container, codec):
    source = generate(
        binaries[0],
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-c:a",
            codec,
            "-metadata",
            "title=Private Title",
        ],
        tmp_path / ("source." + container),
    )
    # A misleading suffix does not choose the parser or the reported source format.
    misleading = tmp_path / "misleading.mp4"
    source.rename(misleading)
    converter = media.MediaMetadataConverter()
    assert converter.validate_input(misleading) == FileFormat(container)
    paths = converter.convert(misleading, tmp_path, {}, lambda _: None, CancellationToken())
    assert paths[0].suffix == ".flac"
    assert "Private" not in paths[1].read_text()


@pytest.mark.parametrize(
    "container,codec",
    [
        ("mp4", "libx264"),
        ("mov", "libx264"),
        ("avi", "mpeg4"),
        ("webm", "libvpx"),
    ],
)
def test_video_containers_without_audio_and_generated_structure(
    tmp_path, binaries, container, codec
):
    source = generate(
        binaries[0],
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=32x24:r=4:d=0.5",
            "-c:v",
            codec,
            "-metadata",
            "title=Private Title",
        ],
        tmp_path / ("source." + container),
    )
    converter = media.MediaMetadataConverter()
    # ffprobe identifies WebM through the common Matroska/WebM demuxer.
    assert converter.validate_input(source) == FileFormat(
        "mkv" if container == "webm" else container
    )
    paths = converter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    after = probe(paths[0], binaries, tmp_path)
    assert [s["codec_name"] for s in after["streams"]] == ["h264"]
    assert "Private" not in json.dumps(after)


def test_m4a_audio_container(tmp_path, binaries):
    source = generate(
        binaries[0],
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.2",
            "-c:a",
            "aac",
            "-metadata",
            "artist=Private Owner",
        ],
        tmp_path / "source.m4a",
    )
    converter = media.MediaMetadataConverter()
    assert converter.validate_input(source) == FileFormat.M4A
    paths = converter.convert(source, tmp_path, {}, lambda _: None, CancellationToken())
    assert paths[0].suffix == ".flac"
    assert "Private" not in paths[1].read_text()


def test_reject_corrupt_and_playlist_even_with_supported_suffix(tmp_path, binaries):
    converter = media.MediaMetadataConverter()
    path = tmp_path / "source.mp4"
    for data in (
        b"not media",
        b"\x00\x00\x00\x18ftypisom",
        b"#EXTM3U\nhttps://example.test/a.mp4\n",
    ):
        path.write_bytes(data)
        with pytest.raises(ConversionError) as error:
            converter.convert(path, tmp_path, {}, lambda _: None, CancellationToken())
        assert error.value.code == ErrorCode.INVALID_INPUT
    assert list(tmp_path.iterdir()) == [path]


def test_missing_binaries_and_unknown_options(monkeypatch, tmp_path):
    converter = media.MediaMetadataConverter()
    monkeypatch.setattr(media, "find_ffmpeg", lambda: None)
    with pytest.raises(ConversionError, match="not installed"):
        converter.convert(
            tmp_path / "missing.mp4", tmp_path, {}, lambda _: None, CancellationToken()
        )
    for options in ({"unknown": True}, {"timeout": True}, {"timeout": 4}, {"timeout": 601}):
        with pytest.raises(ConversionError) as error:
            converter.validate_options(options)
        assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_source_byte_pixel_and_duration_limits(tmp_path, binaries, video_source, monkeypatch):
    converter = media.MediaMetadataConverter()
    monkeypatch.setattr(media, "MAX_BYTES", 1)
    with pytest.raises(ConversionError, match="512 MiB"):
        converter.validate_input(video_source)
    monkeypatch.setattr(media, "MAX_BYTES", 512 * 1024 * 1024)
    monkeypatch.setattr(media, "MAX_PIXELS", 10)
    with pytest.raises(ConversionError, match="pixel"):
        converter.convert(video_source, tmp_path, {}, lambda _: None, CancellationToken())
    monkeypatch.setattr(media, "MAX_PIXELS", 40_000_000)
    monkeypatch.setattr(media, "MAX_DURATION", 0.1)
    with pytest.raises(ConversionError, match="one hour"):
        converter.convert(video_source, tmp_path, {}, lambda _: None, CancellationToken())
    assert not list(tmp_path.glob("clean-media-*"))
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_precancel_and_cancel_before_probe_publish_nothing(tmp_path, binaries, audio_source):
    converter = media.MediaMetadataConverter()
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ConversionCancelled):
        converter.convert(tmp_path / "missing.mp4", tmp_path, {}, lambda _: None, token)
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        converter.convert(audio_source, tmp_path, {}, lambda _: token.cancel(), token)
    assert not list(tmp_path.glob("clean-media-*"))
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_cancel_after_transcode_and_failed_verification_publish_nothing(
    tmp_path,
    binaries,
    audio_source,
    monkeypatch,
):
    original_execute = media._execute
    token = CancellationToken()

    def cancel_after_transcode(command, timeout, current_token):
        original_execute(command, timeout, current_token)
        if Path(command[0]) == binaries[0]:
            token.cancel()

    monkeypatch.setattr(media, "_execute", cancel_after_transcode)
    with pytest.raises(ConversionCancelled):
        media.MediaMetadataConverter().convert(audio_source, tmp_path, {}, lambda _: None, token)
    monkeypatch.setattr(media, "_execute", original_execute)

    def fail_verification(*_):
        raise ConversionError(ErrorCode.CONVERSION_FAILED, "Verification failed")

    monkeypatch.setattr(media, "_verify", fail_verification)
    with pytest.raises(ConversionError, match="Verification failed"):
        media.MediaMetadataConverter().convert(
            audio_source,
            tmp_path,
            {},
            lambda _: None,
            CancellationToken(),
        )
    assert not list(tmp_path.glob("clean-media-*"))
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_output_size_cap_rejects_partial_recording(tmp_path, binaries, audio_source, monkeypatch):
    monkeypatch.setattr(media, "MAX_OUTPUT_BYTES", 1024)
    with pytest.raises(ConversionError, match="output limit"):
        media.MediaMetadataConverter().convert(
            audio_source,
            tmp_path,
            {},
            lambda _: None,
            CancellationToken(),
        )
    assert not list(tmp_path.glob("clean-media-*"))
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_short_output_is_rejected_even_below_size_cap(
    tmp_path,
    binaries,
    audio_source,
    monkeypatch,
):
    original_probe = media._probe

    def truncated_probe(*args, **kwargs):
        info = original_probe(*args, **kwargs)
        if kwargs.get("output"):
            info["streams"][0]["duration"] = "0.01"
            info["format"]["duration"] = "0.01"
        return info

    monkeypatch.setattr(media, "_probe", truncated_probe)
    with pytest.raises(ConversionError, match="duration differs"):
        media.MediaMetadataConverter().convert(
            audio_source,
            tmp_path,
            {},
            lambda _: None,
            CancellationToken(),
        )
    assert not list(tmp_path.glob("clean-media-*"))


def test_report_collision_rolls_back_media_without_overwriting(
    tmp_path,
    binaries,
    audio_source,
    monkeypatch,
):
    class FixedId:
        hex = "0123456789abcdef"

    monkeypatch.setattr(media, "uuid4", FixedId)
    existing = tmp_path / "clean-media-0123456789ab.report.json"
    existing.write_text("existing", encoding="utf-8")
    with pytest.raises(ConversionError) as error:
        media.MediaMetadataConverter().convert(
            audio_source,
            tmp_path,
            {},
            lambda _: None,
            CancellationToken(),
        )
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert existing.read_text() == "existing"
    assert not (tmp_path / "clean-media-0123456789ab.flac").exists()
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


@pytest.mark.parametrize("timeout,cancel", [(0.1, False), (10, True)])
def test_process_timeout_and_cancellation_terminate_child(timeout, cancel, tmp_path):
    token = CancellationToken()
    pidfile = tmp_path / "child.pid"
    # The test process is the same process-group child that FFmpeg would be.
    code = (
        "import os,pathlib,sys,time;"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(30)"
    )
    timer = threading.Timer(0.2, token.cancel) if cancel else None
    if timer:
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ConversionCancelled if cancel else ConversionError) as error:
            media._execute([sys.executable, "-c", code, str(pidfile)], timeout, token)
        assert error.value.code == (ErrorCode.CANCELLED if cancel else ErrorCode.CONVERSION_FAILED)
        assert time.monotonic() - started < 5
        if not cancel:
            assert "timed out" in str(error.value)
        if os.name != "nt" and pidfile.exists():
            with pytest.raises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)
    finally:
        if timer:
            timer.cancel()


def test_output_verifier_rejects_source_tags_and_extra_tracks():
    clean = {
        "format": {"format_name": "flac", "duration": "1"},
        "streams": [
            {
                "index": 0,
                "codec_type": "audio",
                "codec_name": "flac",
                "channels": 1,
                "sample_rate": "44100",
            },
        ],
    }
    media._verify(clean, False, True)
    clean["format"]["tags"] = {"artist": "Private Owner"}
    with pytest.raises(ConversionError, match="metadata"):
        media._verify(clean, False, True)
    clean["format"].pop("tags")
    clean["streams"].append({"codec_type": "subtitle"})
    with pytest.raises(ConversionError, match="tracks"):
        media._verify(clean, False, True)
