"""Reproducible runtime and sampled process RSS baseline; no document text logged."""

import argparse
import json
import multiprocessing
import platform
import tempfile
import time
from pathlib import Path

import psutil
import pymupdf

from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
from local_pdf_toolkit.core.contracts import CancellationToken
from local_pdf_toolkit.core.formats import FileFormat


def convert(source, folder):
    PdfImagesConverter(FileFormat.JPEG).convert(
        Path(source), Path(folder), {"dpi": 150}, lambda _: None, CancellationToken()
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        source = args.input
        if source is None:
            source = root / "synthetic-100.pdf"
            with pymupdf.open() as doc:
                for index in range(100):
                    doc.new_page().insert_text((72, 72), f"Benchmark page {index + 1}")
                doc.save(source)
        results = []
        for label in ("first_run", "repeat_run"):
            output = root / label
            output.mkdir()
            process = multiprocessing.get_context("spawn").Process(
                target=convert, args=(source, output)
            )
            started = time.perf_counter()
            process.start()
            peak = 0
            observed = psutil.Process(process.pid)
            while process.is_alive():
                try:
                    peak = max(peak, observed.memory_info().rss)
                except psutil.NoSuchProcess:
                    pass
                time.sleep(0.02)
            process.join()
            outputs = list(output.glob("*.jpg"))
            results.append(
                {
                    "run": label,
                    "seconds": round(time.perf_counter() - started, 3),
                    "peak_rss_mib_sampled": round(peak / 1024**2, 2),
                    "output_count": len(outputs),
                    "exit_code": process.exitcode,
                    "output_bytes": sum(p.stat().st_size for p in outputs),
                }
            )
            if process.exitcode:
                raise RuntimeError("Benchmark conversion failed")
        report = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pymupdf": pymupdf.VersionBind,
            "input": "uploaded" if args.input else "synthetic-100",
            "input_bytes": source.stat().st_size,
            "dpi": 150,
            "quality": 85,
            "rss_sampling_ms": 20,
            "runs": results,
            "note": "Includes spawned-process startup. OS filesystem caches not flushed.",
        }
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
