import hashlib
import os
import sys
import threading
import time
from types import SimpleNamespace

import pymupdf
import pytest

from local_pdf_toolkit.converters import ocr
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.errors import ConversionCancelled, ConversionError, ErrorCode
from local_pdf_toolkit.core.formats import FileFormat


@pytest.fixture
def scanned_pdf(tmp_path):
    """A raster-only PDF made locally, with no hidden searchable text."""
    path = tmp_path / "scan.pdf"
    with pymupdf.open() as original, pymupdf.open() as scan:
        page = original.new_page(width=420, height=300)
        page.insert_text((35, 90), "SEARCHABLE ENGINE TEST", fontsize=23)
        page.insert_text((35, 135), "Offline document 12345", fontsize=21)
        image = page.get_pixmap(dpi=150)
        page = scan.new_page(width=440, height=340)
        page.set_cropbox(pymupdf.Rect(10, 20, 430, 320))
        page.insert_image(page.rect, stream=image.tobytes("png"))
        page.set_rotation(90)
        scan.save(path)
    return path


@pytest.fixture
def engine():
    binary = ocr.find_tesseract()
    if binary is None:
        pytest.skip("Tesseract is not installed locally")
    languages = ocr._run([str(binary), "--list-langs"], 5, CancellationToken()).splitlines()
    if "eng" not in languages:
        pytest.skip("Tesseract English language pack is not installed")
    return binary


def test_capability_and_defaults():
    converter = ocr.OcrConverter()
    assert ocr.ocr_converters()[0].spec == converter.spec
    assert converter.spec.operation_id == "pdf.ocr"
    assert converter.spec.input_formats == converter.spec.output_formats == (FileFormat.PDF,)
    assert converter.validate_options({}) == {
        "language": "eng",
        "dpi": 150,
        "timeout": 60,
        "skip_existing_text": True,
    }
    assert any("mixed" in text for text in converter.spec.limitations)
    assert any("misread" in text for text in converter.spec.limitations)


@pytest.mark.parametrize(
    "options",
    [
        {"language": "eng;echo"},
        {"language": "../../eng"},
        {"language": "eng\nfra"},
        {"language": ""},
        {"language": "+eng"},
        {"language": "eng++fra"},
        {"language": "a" * 129},
        {"language": 1},
        {"dpi": True},
        {"dpi": 72},
        {"timeout": 4},
        {"timeout": 121},
        {"timeout": 5.0},
        {"skip_existing_text": "yes"},
        {"extra": False},
    ],
)
def test_invalid_options(options):
    with pytest.raises(ConversionError) as error:
        ocr.OcrConverter().validate_options(options)
    assert error.value.code == ErrorCode.INVALID_OPTIONS


def test_missing_engine_is_actionable(scanned_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    with pytest.raises(ConversionError, match="not installed") as error:
        ocr.OcrConverter().convert(scanned_pdf, tmp_path, {}, lambda _: None, CancellationToken())
    assert error.value.code == ErrorCode.CONVERSION_FAILED
    assert list(tmp_path.iterdir()) == [scanned_pdf]


@pytest.mark.parametrize("variable", ["PROGRAMFILES", "PROGRAMFILES(X86)"])
def test_windows_installation_discovery(tmp_path, monkeypatch, variable):
    executable = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(ocr.shutil, "which", lambda _: None)
    monkeypatch.setattr(ocr, "os", SimpleNamespace(name="nt", environ={variable: str(tmp_path)}))
    assert ocr.find_tesseract() == executable


def test_missing_language_pack_is_actionable(scanned_pdf, tmp_path, engine):
    with pytest.raises(ConversionError, match="language packs are not installed") as error:
        ocr.OcrConverter().convert(
            scanned_pdf,
            tmp_path,
            {"language": "missing_langpack"},
            lambda _: None,
            CancellationToken(),
        )
    assert error.value.code == ErrorCode.INVALID_OPTIONS
    assert list(tmp_path.iterdir()) == [scanned_pdf]


@pytest.mark.parametrize("dpi", [150, 300])
@pytest.mark.parametrize("user_unit", [1, 2])
def test_real_ocr_searchable_geometry_and_original(scanned_pdf, tmp_path, engine, dpi, user_unit):
    if user_unit != 1:
        with pymupdf.open(scanned_pdf) as source:
            source.xref_set_key(source[0].xref, "UserUnit", str(user_unit))
            source.saveIncr()
    before = hashlib.sha256(scanned_pdf.read_bytes()).digest()
    updates = []
    paths = ocr.OcrConverter().convert(
        scanned_pdf,
        tmp_path,
        {"dpi": dpi},
        updates.append,
        CancellationToken(),
    )
    assert paths == (tmp_path / "scan_searchable.pdf",)
    with pymupdf.open(scanned_pdf) as source, pymupdf.open(paths[0]) as result:
        assert not source[0].get_text().strip()
        assert "SEARCHABLE ENGINE TEST" in result[0].get_text()
        assert "12345" in result[0].get_text()
        assert result[0].mediabox == source[0].mediabox
        assert result[0].cropbox == source[0].cropbox
        assert result[0].rotation == source[0].rotation == 90
        assert result[0].rect == source[0].rect
        # The visible page and hidden text occupy the same rotated crop area.
        assert all(
            result[0].rect.contains(pymupdf.Rect(word[:4]) * result[0].rotation_matrix)
            for word in result[0].get_text("words")
        )
        original_image = source[0].get_pixmap(dpi=72)
        output_image = result[0].get_pixmap(dpi=72)
        assert (output_image.width, output_image.height) == (
            original_image.width,
            original_image.height,
        )
        assert (
            sum(
                abs(a - b)
                for a, b in zip(
                    original_image.samples,
                    output_image.samples,
                    strict=True,
                )
            )
            / len(original_image.samples)
            < 5
        )
    assert hashlib.sha256(scanned_pdf.read_bytes()).digest() == before
    assert updates[-1].completed == updates[-1].total == 1
    assert sorted(path.name for path in tmp_path.iterdir()) == ["scan.pdf", "scan_searchable.pdf"]


def test_mixed_document_copies_existing_text_page(scanned_pdf, tmp_path, engine):
    with pymupdf.open(scanned_pdf) as document:
        page = document.new_page(width=280, height=160)
        page.insert_text((20, 40), "Existing exact searchable text", fontsize=12)
        page.set_rotation(270)
        mixed = tmp_path / "mixed.pdf"
        document.save(mixed)
    before = mixed.read_bytes()
    (path,) = ocr.OcrConverter().convert(mixed, tmp_path, {}, lambda _: None, CancellationToken())
    with pymupdf.open(mixed) as source, pymupdf.open(path) as result:
        assert "SEARCHABLE" in result[0].get_text()
        assert result[1].get_text() == source[1].get_text()
        assert result[1].get_contents()
        assert result[1].get_pixmap().samples == source[1].get_pixmap().samples
        assert result[1].rotation == source[1].rotation == 270
        assert result[1].rect == source[1].rect
    assert mixed.read_bytes() == before


def test_existing_text_can_be_rasterized(tmp_path, engine):
    source = tmp_path / "text.pdf"
    with pymupdf.open() as document:
        document.new_page(width=420, height=200).insert_text(
            (30, 80),
            "SEARCHABLE ENGINE TEST",
            fontsize=23,
        )
        document.save(source)
    (path,) = ocr.OcrConverter().convert(
        source,
        tmp_path,
        {"skip_existing_text": False},
        lambda _: None,
        CancellationToken(),
    )
    with pymupdf.open(path) as result:
        assert result[0].get_images()
        assert "SEARCHABLE ENGINE TEST" in result[0].get_text()


def test_existing_output_preserved(scanned_pdf, tmp_path, engine):
    existing = tmp_path / "scan_searchable.pdf"
    existing.write_bytes(b"keep")
    with pytest.raises(ConversionError) as error:
        ocr.OcrConverter().convert(scanned_pdf, tmp_path, {}, lambda _: None, CancellationToken())
    assert error.value.code == ErrorCode.OUTPUT_ERROR
    assert existing.read_bytes() == b"keep"
    assert not list(tmp_path.glob(".pdf-toolkit-*"))


def test_pre_cancel_without_engine(scanned_pdf, tmp_path, monkeypatch):
    token = CancellationToken()
    token.cancel()
    monkeypatch.setattr(ocr, "find_tesseract", lambda: pytest.fail("Engine should not start"))
    with pytest.raises(ConversionCancelled):
        ocr.OcrConverter().convert(scanned_pdf, tmp_path, {}, lambda _: None, token)
    assert list(tmp_path.iterdir()) == [scanned_pdf]


def test_cancellation_after_page_discards_output(scanned_pdf, tmp_path, engine):
    token = CancellationToken()

    def cancel(update):
        if update.completed:
            token.cancel()

    with pytest.raises(ConversionCancelled):
        ocr.OcrConverter().convert(scanned_pdf, tmp_path, {}, cancel, token)
    assert list(tmp_path.iterdir()) == [scanned_pdf]


@pytest.mark.parametrize("mode", ["timeout", "cancel", "invalid_pdf"])
def test_engine_failure_discards_staging(scanned_pdf, tmp_path, engine, monkeypatch, mode):
    before = scanned_pdf.read_bytes()
    run = ocr._run

    def fail_page(command, timeout, token, *, output_path=None):
        if output_path is None:
            return run(command, timeout, token)
        if mode == "timeout":
            return run([sys.executable, "-c", "import time; time.sleep(30)"], 0.1, token)
        if mode == "cancel":
            token.cancel()
            token.raise_if_cancelled()
        output_path.write_bytes(b"invalid PDF engine output")
        return ""

    monkeypatch.setattr(ocr, "_run", fail_page)
    with pytest.raises(ConversionError):
        ocr.OcrConverter().convert(scanned_pdf, tmp_path, {}, lambda _: None, CancellationToken())
    assert scanned_pdf.read_bytes() == before
    assert list(tmp_path.iterdir()) == [scanned_pdf]


def test_page_and_pixel_limits(scanned_pdf, tmp_path, engine, monkeypatch):
    monkeypatch.setattr(ocr, "MAX_PIXELS", 1)
    with pytest.raises(ConversionError, match="pixels"):
        ocr.OcrConverter().convert(scanned_pdf, tmp_path, {}, lambda _: None, CancellationToken())
    assert list(tmp_path.iterdir()) == [scanned_pdf]
    monkeypatch.setattr(ocr, "MAX_PAGES", 0)
    with pytest.raises(ConversionError, match="page limit"):
        ocr.OcrConverter().validate_input(scanned_pdf)


def test_encrypted_and_corrupt_rejected(scanned_pdf, tmp_path):
    locked = tmp_path / "locked.pdf"
    with pymupdf.open(scanned_pdf) as document:
        document.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret")
    with pytest.raises(ConversionError) as error:
        ocr.OcrConverter().validate_input(locked)
    assert error.value.code == ErrorCode.PASSWORD_REQUIRED
    corrupt = tmp_path / "corrupt.pdf"
    for content in (b"not PDF", b"%PDF-1.4\nbroken"):
        corrupt.write_bytes(content)
        with pytest.raises(ConversionError) as error:
            ocr.OcrConverter().validate_input(corrupt)
        assert error.value.code == ErrorCode.INVALID_INPUT


@pytest.mark.parametrize("mode", ["timeout", "cancel", "overflow", "failure"])
def test_subprocess_failure_and_cleanup(mode, monkeypatch):
    processes = []
    real_popen = ocr.subprocess.Popen

    def record_process(*args, **kwargs):
        assert isinstance(args[0], list)
        assert not kwargs.get("shell", False)
        process = real_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(ocr.subprocess, "Popen", record_process)
    token = CancellationToken()
    timer = None
    code = "import time; time.sleep(30)"
    expected = ConversionError
    match = "timed out"
    timeout = 0.15
    if mode == "cancel":
        timer = threading.Timer(0.15, token.cancel)
        timer.start()
        expected = ConversionCancelled
        match = "cancelled"
        timeout = 5
    elif mode == "overflow":
        code = "import sys; sys.stdout.buffer.write(b'x' * 1000000); sys.stdout.flush()"
        match = "excessive"
        timeout = 5
    elif mode == "failure":
        code = "raise SystemExit(1)"
        match = "failed"
        timeout = 5
    try:
        with pytest.raises(expected, match=match):
            ocr._run([sys.executable, "-c", code], timeout, token)
    finally:
        if timer:
            timer.cancel()
            timer.join()
    # Windows cleanup launches taskkill through the same patched Popen.
    workers = [process for process in processes if process.args[0] == sys.executable]
    assert len(workers) == 1
    assert all(process.poll() is not None for process in processes)
    assert workers[0].stdout.closed


@pytest.mark.skipif(os.name == "nt", reason="POSIX process group assertion")
def test_timeout_terminates_descendant(tmp_path):
    psutil = pytest.importorskip("psutil")
    pidfile = tmp_path / "child.pid"
    code = (
        "import pathlib,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)"
    )
    with pytest.raises(ConversionError, match="timed out"):
        ocr._run([sys.executable, "-c", code, str(pidfile)], 0.5, CancellationToken())
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 2
    while psutil.pid_exists(pid):
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        assert time.monotonic() < deadline, "Tesseract descendant remains running"
        time.sleep(0.05)


def test_engine_output_file_size_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "MAX_OCR_PAGE_BYTES", 10)
    produced = tmp_path / "oversized.pdf"
    code = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_bytes(b'x'*100)"
    with pytest.raises(ConversionError, match="size limit"):
        ocr._run(
            [sys.executable, "-c", code, str(produced)],
            5,
            CancellationToken(),
            output_path=produced,
        )
