"""Batch naming previews must match safe, unchanged-byte publication."""

from pathlib import Path

import pytest
from PIL import Image

from local_pdf_toolkit.converters.rename_copies import BatchRenameConverter, plan_names
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode


@pytest.fixture
def sources(tmp_path, fixture_dir):
    source = tmp_path / "inputs"
    source.mkdir()
    pdf = source / "Original.PDF"
    pdf.write_bytes((fixture_dir / "one_page.pdf").read_bytes())
    png = source / "Photo.png"
    Image.new("RGB", (10, 20), "red").save(png)
    destination = tmp_path / "copies"
    destination.mkdir()
    return (pdf, png), destination


def run(paths, destination, options=None, progress=None, token=None):
    return BatchRenameConverter().convert(
        paths,
        destination,
        options or {},
        progress or (lambda _: None),
        token or CancellationToken(),
    )


def test_preview_matches_ordered_mixed_format_copies_and_preserves_originals(sources):
    paths, destination = sources
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    options = {
        "base_name": "Trip",
        "prefix": "Summer ",
        "suffix": " final",
        "start": 8,
        "digits": 3,
    }
    names = plan_names(paths[::-1], options)
    assert names == ("Summer Trip final-008.png", "Summer Trip final-009.PDF")
    results = run(paths[::-1], destination, options)
    assert tuple(path.name for path in results) == names
    for source, result in zip(paths[::-1], results, strict=True):
        assert result.read_bytes() == source.read_bytes()
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths} == before
    assert plan_names(paths, {}) == ("Original-001.PDF", "Photo-002.png")


@pytest.mark.parametrize(
    "options",
    [
        {"base_name": "../escape"},
        {"base_name": "CON"},
        {"prefix": "x\\escape"},
        {"suffix": "\x00"},
        {"digits": True},
        {"digits": 9},
        {"start": 0},
        {"start": 1.5},
        {"start": 99999999},  # The second file would overflow the bounded number.
        {"base_name": "a" * 200},  # Number and extension must also fit.
        {"unknown": 1},
    ],
)
def test_invalid_name_or_numbering_options_fail_before_copying(sources, options):
    paths, destination = sources
    with pytest.raises(ConversionError) as error:
        run(paths, destination, options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS
    assert not list(destination.iterdir())


def test_existing_case_variant_collision_preserves_all_files(sources):
    paths, destination = sources
    occupied = destination / "PHOTO-002.PNG"
    occupied.write_bytes(b"existing")
    with pytest.raises(ConversionError) as error:
        run(paths, destination)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert list(destination.iterdir()) == [occupied]
    assert occupied.read_bytes() == b"existing"


def test_collision_during_publication_rolls_back_only_own_outputs(sources, monkeypatch):
    import local_pdf_toolkit.core.output as publication

    paths, destination = sources
    real_link = publication.os.link
    collision = destination / "Photo-002.png"

    def competing_writer(source, target):
        if Path(target) == collision:
            collision.write_bytes(b"other job")
        return real_link(source, target)

    monkeypatch.setattr(publication.os, "link", competing_writer)
    with pytest.raises(ConversionError) as error:
        run(paths, destination)
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert list(destination.iterdir()) == [collision]
    assert collision.read_bytes() == b"other job"


def test_cancel_after_first_copy_removes_staging_without_publishing(sources):
    paths, destination = sources
    token = CancellationToken()
    with pytest.raises(ConversionCancelled):
        run(paths, destination, token=token, progress=lambda _: token.cancel())
    assert not list(destination.iterdir())
    assert all(path.is_file() for path in paths)


def test_changed_input_rejects_whole_batch(sources):
    paths, destination = sources
    original = paths[0].read_bytes()

    def external_change(progress):
        if progress.completed == 1:
            paths[1].write_bytes(b"changed externally")

    with pytest.raises(ConversionError) as error:
        run(paths, destination, progress=external_change)
    assert error.value.code == ErrorCode.INVALID_INPUT
    assert not list(destination.iterdir())
    assert paths[0].read_bytes() == original


def test_corrupt_later_input_publishes_nothing(sources):
    paths, destination = sources
    paths[1].write_bytes(b"not an image")
    with pytest.raises(ConversionError):
        run(paths, destination)
    assert not list(destination.iterdir())


def test_duplicate_sources_are_rejected_in_preview_and_worker(sources):
    paths, destination = sources
    with pytest.raises(ConversionError, match="only once"):
        plan_names((paths[0], paths[0]), {})
    alias = paths[0].parent / "alias.pdf"
    alias.hardlink_to(paths[0])
    with pytest.raises(ConversionError, match="only once"):
        run((paths[0], alias), destination)
    assert not list(destination.iterdir())


def test_overlong_windows_destination_is_rejected_before_copy(sources):
    paths, destination = sources
    # Keep the folder itself within the legacy Windows limit, then exceed it
    # only when appending the output filename.
    nested = destination / ("a" * (245 - len(str(destination)) - 1))
    nested.mkdir(parents=True)
    with pytest.raises(ConversionError) as error:
        run(paths, nested)
    assert error.value.code == ErrorCode.INVALID_OPTIONS
    assert not list(nested.iterdir())
