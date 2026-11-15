"""Offline synthetic benchmarks. Run with the project's Python; see README.md."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "import_app",
    "build_registry",
    "text100",
    "scan20",
    "image12mp",
    "pdf_docx",
    "office_pdf",
    "ocr",
    "media",
    "qt_soak",
)
HEAVY = {"text100", "scan20", "ocr", "qt_soak"}


def fixtures(root):
    import io
    import wave

    import pymupdf
    from PIL import Image, ImageDraw

    with pymupdf.open() as doc:
        for index in range(100):
            page = doc.new_page()
            page.insert_text((72, 72), f"Synthetic benchmark page {index + 1}")
            page.insert_textbox((72, 100, 520, 750), "Offline sample text. " * 150)
        doc.save(root / "text.pdf", no_new_id=True)
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    for y in range(70, 1600, 40):
        draw.text((70, y), "Synthetic scanned benchmark text 1234567890", fill="black")
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=85)
    with pymupdf.open() as doc:
        for _ in range(20):
            doc.new_page().insert_image((0, 0, 595, 842), stream=stream.getvalue())
        doc.save(root / "scan.pdf", no_new_id=True)
    # Deterministic gradients avoid an unrealistically cheap uniform image.
    image = Image.linear_gradient("L").resize((4000, 3000)).convert("RGB")
    ImageDraw.Draw(image).rectangle((100, 100, 2000, 1500), fill=(40, 100, 160))
    image.save(root / "image.png")
    (root / "office.txt").write_text("Synthetic offline Office benchmark.\n" * 100)
    with wave.open(str(root / "audio.wav"), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 16000)


def qt_soak(root, count):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from local_pdf_toolkit.converters.preview import PreviewConverter
    from local_pdf_toolkit.core.jobs import JobController

    app = QApplication.instance() or QApplication([])
    jobs = JobController()
    pulse = QTimer()
    pulse.setInterval(5)
    gaps, rss, outcomes = [], [], []
    previous = time.perf_counter()

    def heartbeat():
        nonlocal previous
        now = time.perf_counter()
        gaps.append((now - previous) * 1000)
        previous = now

    pulse.timeout.connect(heartbeat)
    pulse.start()
    for index in range(count):
        destination = root / f"qt-{index}"
        destination.mkdir()
        loop = QEventLoop()
        result = []

        def finished(paths, error, result=result, loop=loop):
            result.append(error[0] if error else "ok")
            loop.quit()

        jobs.finished.connect(finished)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(15000)
        jobs.start(PreviewConverter(), root / "text.pdf", destination, {})
        if index % 2:
            jobs.cancel()
        loop.exec()
        timeout.stop()
        jobs.finished.disconnect(finished)
        if not result or jobs.running:
            jobs.cancel()
            raise RuntimeError("Qt soak worker timed out")
        expected = "cancelled" if index % 2 else "ok"
        if result[0] != expected:
            raise RuntimeError("Unexpected Qt soak outcome")
        outcomes.extend(result)
        shutil.rmtree(destination)
        app.processEvents()
        rss.append(psutil.Process().memory_info().rss)
    pulse.stop()
    return {
        "jobs": count,
        "completed": outcomes.count("ok"),
        "cancelled": outcomes.count("cancelled"),
        "heartbeat_count": len(gaps),
        "heartbeat_max_ms": max(gaps, default=0),
        "heartbeat_p95_ms": sorted(gaps)[int((len(gaps) - 1) * 0.95)] if gaps else 0,
        "parent_rss_first_last_mib": [rss[0] / 2**20, rss[-1] / 2**20],
        "remaining_children": len(psutil.Process().children(recursive=True)),
        "alive_job_process": jobs.running,
    }


def worker(case, root, output, soak_jobs):
    if case == "import_app":
        import local_pdf_toolkit.app  # noqa: F401

        return {}
    if case == "build_registry":
        from local_pdf_toolkit.app import build_registry

        build_registry()
        return {}
    if case == "qt_soak":
        return qt_soak(root, soak_jobs)
    from local_pdf_toolkit.core.contracts import CancellationToken
    from local_pdf_toolkit.core.formats import FileFormat

    options = {}
    if case in ("text100", "scan20"):
        from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter

        converter = PdfImagesConverter(FileFormat.JPEG)
        source = root / ("text.pdf" if case == "text100" else "scan.pdf")
        options = {"dpi": 150}
    elif case == "image12mp":
        from local_pdf_toolkit.converters.images import ImageConverter

        converter, source = ImageConverter(FileFormat.JPEG), root / "image.png"
    elif case == "pdf_docx":
        from local_pdf_toolkit.converters.pdf_office import PdfOfficeConverter

        converter, source = PdfOfficeConverter(FileFormat.DOCX), root / "text.pdf"
    elif case == "office_pdf":
        from local_pdf_toolkit.converters.office_pdf import OfficePdfConverter

        converter, source = OfficePdfConverter(), root / "office.txt"
    elif case == "ocr":
        from local_pdf_toolkit.converters.ocr import OcrConverter

        converter, source = OcrConverter(), root / "scan.pdf"
    elif case == "media":
        from local_pdf_toolkit.converters.media_metadata import MediaMetadataConverter

        converter, source = MediaMetadataConverter(), root / "audio.wav"
    paths = converter.convert(source, output, options, lambda _: None, CancellationToken())
    return {"output_count": len(paths), "output_bytes": sum(p.stat().st_size for p in paths)}


def sample(case, root, output, args):
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        case,
        "--root",
        str(root),
        "--output",
        str(output),
        "--soak-jobs",
        str(args.soak_jobs),
    ]
    if case in ("import_app", "build_registry"):
        code = "import local_pdf_toolkit.app"
        if case == "build_registry":
            code += "; local_pdf_toolkit.app.build_registry()"
        command = [sys.executable, "-c", code + "; print('{}')"]
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    observed, peak = psutil.Process(process.pid), 0
    while process.poll() is None:
        try:
            tree = [observed, *observed.children(recursive=True)]
            current = 0
            for member in tree:
                try:
                    current += member.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak = max(peak, current)
        except psutil.NoSuchProcess:
            pass
        if time.perf_counter() - started > args.timeout:
            for child in observed.children(recursive=True):
                child.kill()
            process.kill()
            process.communicate()
            raise RuntimeError(f"{case} exceeded timeout")
        time.sleep(0.01)
    stdout, stderr = process.communicate()
    elapsed = time.perf_counter() - started
    if process.returncode:
        # Fixture-only diagnostics; never process user documents with this harness.
        raise RuntimeError(f"{case} failed: {stderr.decode(errors='replace')[-1500:]}")
    return {
        "seconds": elapsed,
        "peak_tree_rss_mib_sampled": peak / 2**20,
        "details": json.loads(stdout),
    }


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--heavy-runs", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--soak-jobs", type=int, default=100)
    parser.add_argument("--worker", choices=CASES, help=argparse.SUPPRESS)
    parser.add_argument("--root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.root, args.output, args.soak_jobs)))
        return
    if args.report is None:
        parser.error("--report is required")
    if min(args.runs, args.heavy_runs, args.soak_jobs) < 1 or args.warmup < 0:
        parser.error("runs and soak-jobs must be positive; warmup must be nonnegative")
    if args.quick:
        args.runs = args.heavy_runs = 1
        args.warmup, args.soak_jobs = 0, min(10, args.soak_jobs)
    packages = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    binaries = {}
    for name in ("tesseract", "ffmpeg", "ffprobe", "soffice", "libreoffice"):
        binary = shutil.which(name)
        if binary:
            version = subprocess.run(
                [
                    binary,
                    "--version" if name in ("tesseract", "soffice", "libreoffice") else "-version",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            binaries[name] = (version.stdout or version.stderr).splitlines()[0]
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "packages": dict(sorted(packages.items())),
        "binaries": binaries,
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": {
            str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "src").rglob("*.py"))
        },
        "harness_sha256": digest(Path(__file__)),
        "results": {},
        "settings": {
            "runs": args.runs,
            "heavy_runs": args.heavy_runs,
            "warmup": args.warmup,
            "soak_jobs": args.soak_jobs,
        },
        "notes": [
            "10 ms RSS sums parent and descendants; shared pages may count twice.",
            "Fresh processes; elapsed includes interpreter startup and shutdown.",
            "Filesystem caches are warm; no cache flushing. Synthetic inputs only.",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="toolkit-benchmark-") as temporary:
        root = Path(temporary)
        fixtures(root)
        report["inputs"] = {
            p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in root.iterdir()
        }
        for case in args.cases:
            missing = (
                (
                    case == "office_pdf"
                    and not any(name in binaries for name in ("soffice", "libreoffice"))
                )
                or (case == "ocr" and "tesseract" not in binaries)
                or (case == "media" and not all(name in binaries for name in ("ffmpeg", "ffprobe")))
            )
            if missing:
                report["results"][case] = {"skipped": "Optional local executable unavailable"}
                continue
            runs = args.heavy_runs if case in HEAVY else args.runs
            samples = []
            for index in range(args.warmup + runs):
                output = root / "output"
                output.mkdir()
                result = sample(case, root, output, args)
                if index >= args.warmup:
                    samples.append(result)
                shutil.rmtree(output)
            report["results"][case] = {
                "samples": samples,
                **{
                    metric: {
                        "median": statistics.median(s[metric] for s in samples),
                        "min": min(s[metric] for s in samples),
                        "max": max(s[metric] for s in samples),
                    }
                    for metric in ("seconds", "peak_tree_rss_mib_sampled")
                },
            }
            print(f"{case}: {report['results'][case]['seconds']['median']:.3f}s", flush=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
    args.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
