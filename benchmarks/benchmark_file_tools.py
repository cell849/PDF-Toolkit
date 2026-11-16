"""Synthetic v0.8 file-copy/parsing diagnostic; no private documents."""

import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil


def worker(mode, source, output):
    from local_pdf_toolkit.converters.file_probe import FileProbeConverter
    from local_pdf_toolkit.converters.rename_copies import BatchRenameConverter
    from local_pdf_toolkit.core.contracts import CancellationToken

    source, output = Path(source), Path(output)
    started = time.perf_counter()
    if mode == "copy_only":
        with source.open("rb") as original, (output / "copy.bmp").open("xb") as target:
            while chunk := original.read(1024 * 1024):
                target.write(chunk)
    elif mode == "probe":
        FileProbeConverter().validate_input(source)
    else:
        BatchRenameConverter().convert((source,), output, {}, lambda _: None, CancellationToken())
    print(json.dumps({"operation_seconds": time.perf_counter() - started}))


def main():
    from PIL import Image

    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name) for name in ("Pillow", "PyMuPDF", "psutil")
        },
        "fixture": "synthetic 4096x4096 RGB BMP (48 MiB uncompressed)",
        "sampling_ms": 5,
        "notes": [
            "Three fresh subprocess samples per operation; no discarded warmup.",
            "Elapsed operation time excludes interpreter/import startup; RSS includes imports.",
            "RSS sampled every 5 ms; peaks may be missed. Warm caches are not flushed.",
            "copy_only uses the same 1 MiB Python loop without validation/publication.",
            "probe copies into one snapshot before parsing; "
            "rename copies then probe snapshots again.",
            "Diagnostic comparison on one synthetic input; no optimization claim.",
        ],
    }
    with tempfile.TemporaryDirectory(prefix="file-tool-benchmark-") as folder:
        root = Path(folder)
        source = root / "source.bmp"
        with Image.linear_gradient("L").resize((4096, 4096)).convert("RGB") as image:
            image.save(source)
        report["input_bytes"] = source.stat().st_size
        with source.open("rb") as original:
            report["input_sha256"] = hashlib.file_digest(original, "sha256").hexdigest()
        report["samples"] = {}
        for mode in ("copy_only", "probe", "rename"):
            samples = []
            for index in range(3):
                output = root / f"{mode}-{index}"
                output.mkdir()
                child = subprocess.Popen(
                    [sys.executable, __file__, "worker", mode, str(source), str(output)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                observed = psutil.Process(child.pid)
                peak = 0
                while child.poll() is None:
                    try:
                        peak = max(peak, observed.memory_info().rss)
                    except psutil.NoSuchProcess:
                        pass
                    time.sleep(0.005)
                stdout, stderr = child.communicate(timeout=10)
                if child.returncode:
                    raise RuntimeError(stderr)
                sample = json.loads(stdout)
                sample["peak_rss_mib_sampled"] = peak / 1024**2
                samples.append(sample)
            report["samples"][mode] = samples
        report["medians"] = {
            mode: {
                key: statistics.median(sample[key] for sample in samples)
                for key in ("operation_seconds", "peak_rss_mib_sampled")
            }
            for mode, samples in report["samples"].items()
        }
    Path(sys.argv[1]).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["medians"], indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker(*sys.argv[2:])
    else:
        main()
