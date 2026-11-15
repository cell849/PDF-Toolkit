"""Bounded offline parser probes; native parsing always runs in a fresh process."""

import argparse
import hashlib
import json
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def probe(kind, path):
    from local_pdf_toolkit.core.errors import ConversionError

    try:
        if kind == "pdf":
            from local_pdf_toolkit.converters.pdf_images import PdfImagesConverter
            from local_pdf_toolkit.core.formats import FileFormat

            PdfImagesConverter(FileFormat.PNG).validate_input(path)
        else:
            from local_pdf_toolkit.converters.image_metadata import ImageMetadataConverter

            ImageMetadataConverter().validate_input(path)
        return "accepted"
    except ConversionError:
        return "rejected"


def png_seed():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\x80\x40\x20" * 32) * 32))
        + chunk(b"IEND", b"")
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--seed", type=int, default=849)
    parser.add_argument("--report", type=Path, default=ROOT / "quality/fuzz-linux.json")
    parser.add_argument("--probe", nargs=2, metavar=("KIND", "FILE"))
    args = parser.parse_args()
    if args.probe:
        print(probe(args.probe[0], Path(args.probe[1])))
        return
    if not 1 <= args.seconds <= 1800:
        parser.error("Use a budget between 1 and 1800 seconds.")
    seeds = [("pdf", (ROOT / "tests/fixtures/one_page.pdf").read_bytes()), ("png", png_seed())]
    rng = random.Random(args.seed)
    counts = {"accepted": 0, "rejected": 0}
    failures = []
    started = time.monotonic()
    index = 0
    with tempfile.TemporaryDirectory(prefix="toolkit-fuzz-") as temporary:
        path = Path(temporary) / "probe.data"
        while time.monotonic() - started < args.seconds:
            kind, original = seeds[index % len(seeds)]
            data = bytearray(original)
            operation = rng.randrange(3)
            if operation == 0:
                del data[rng.randrange(len(data)) :]
            elif operation == 1:
                for _ in range(rng.randint(1, 8)):
                    data[rng.randrange(len(data))] ^= rng.randrange(1, 256)
            else:
                offset = rng.randrange(len(data))
                data[offset:offset] = rng.randbytes(rng.randint(1, 32))
            path.write_bytes(data)
            before = hashlib.sha256(data).hexdigest()
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--probe", kind, str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
            )
            observer = psutil.Process(process.pid)
            deadline = time.monotonic() + 3
            failure = None
            while process.poll() is None:
                try:
                    if observer.memory_info().rss > 512 * 1024 * 1024:
                        failure = "memory_limit"
                except psutil.NoSuchProcess:
                    pass
                if time.monotonic() > deadline:
                    failure = "timeout"
                if failure:
                    process.kill()
                    break
                time.sleep(0.01)
            output, _ = process.communicate(timeout=3)
            outcome = output.decode(errors="replace").strip().splitlines()[-1:]
            if failure is None and (process.returncode or not outcome or outcome[0] not in counts):
                failure = "unexpected_exit"
            if hashlib.sha256(path.read_bytes()).hexdigest() != before:
                failure = "source_modified"
            if failure:
                failures.append({"case": index, "kind": kind, "reason": failure, "sha256": before})
                saved = args.report.parent / "fuzz-failures"
                saved.mkdir(parents=True, exist_ok=True)
                (saved / f"{args.seed}-{index}.{kind}").write_bytes(data)
            else:
                counts[outcome[0]] += 1
            index += 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "seed": args.seed,
                "cases": index,
                "outcomes": counts,
                "failures": failures,
                "seconds": round(time.monotonic() - started, 2),
                "limits": "3 seconds and 512 MiB sampled RSS per parser; "
                "bounded small synthetic mutations",
            },
            indent=2,
        )
        + "\n"
    )
    print(f"{index} probes; {len(failures)} failures", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
