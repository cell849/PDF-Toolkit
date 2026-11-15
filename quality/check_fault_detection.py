"""Check that deliberately broken copies fail tests; never edit the working tree."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    (
        "overwrite_existing",
        "core/output.py",
        "os.link(self.staging / name, destination)",
        "__import__('shutil').copyfile(self.staging / name, destination)",
        "tests/quality_properties/test_properties.py::test_publication_collision_rolls_back_only_own_files",
    ),
    (
        "ignore_cancel",
        "core/contracts.py",
        "if self.is_cancelled:",
        "if False:",
        "tests/test_contracts.py::test_cancellation_is_cooperative_and_tokens_are_independent",
    ),
    (
        "copy_image_metadata",
        "converters/image_metadata.py",
        "    try:\n        with warnings.catch_warnings():",
        "    return data\n    try:\n        with warnings.catch_warnings():",
        "tests/test_image_metadata.py::test_jpeg_exif_gps_comments_and_trailing_data_removed",
    ),
    (
        "wrong_redaction_page",
        "converters/redaction.py",
        "marks.get(index, ())",
        "marks.get(index + 1, ())",
        "tests/quality_integrity/test_independent_pdf_outputs.py::test_redaction_independent_renderer_has_opaque_display_space_mask",
    ),
    (
        "ignore_source_digest",
        "converters/redaction.py",
        "if expected_sha256 and digest.hexdigest() != expected_sha256:",
        "if False:",
        "tests/test_redaction.py::test_same_size_and_timestamp_source_change_is_rejected_before_parser_open",
    ),
    (
        "ignore_pixel_budget",
        "converters/compress.py",
        "MAX_PIXELS =",
        "MAX_PIXELS =",
        "tests/quality_integrity/test_compression_limits.py",
    ),
)


def run_tests(selection, source, timeout):
    env = dict(os.environ, PYTHONPATH=str(source), QT_QPA_PLATFORM="offscreen")
    return subprocess.run(
        [sys.executable, "-m", "pytest", *selection, "-q", "--maxfail=1", "--timeout=15"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    selections = list(dict.fromkeys(case[4] for case in CASES))
    baseline = run_tests(selections, ROOT / "src", 90)
    if baseline.returncode:
        print(baseline.stdout[-6000:], baseline.stderr[-1000:])
        raise SystemExit("Healthy baseline failed; fault detection cannot be scored.")
    results = []
    for name, relative, old, new, test in CASES:
        with tempfile.TemporaryDirectory(prefix="toolkit-fault-") as directory:
            source = Path(directory) / "src"
            shutil.copytree(ROOT / "src", source, ignore=shutil.ignore_patterns("__pycache__"))
            path = source / "local_pdf_toolkit" / relative
            text = path.read_text(encoding="utf-8")
            if name == "ignore_pixel_budget":
                # Both continuous and rounded guards must be broken for this seed.
                text = text.replace("MAX_PIXELS /", "4_000_000_000 /")
                text = text.replace("> MAX_PIXELS", "> 4_000_000_000")
            else:
                if text.count(old) != 1:
                    raise SystemExit(f"Fault anchor changed: {name}")
                text = text.replace(old, new)
            path.write_text(text, encoding="utf-8")
            result = run_tests([test], source, 45)
            detected = result.returncode == 1 and " failed" in result.stdout
            if "ERROR collecting" in result.stdout or "ImportError" in result.stdout:
                detected = False
            results.append(
                {
                    "fault": name,
                    "detected": detected,
                    "pytest_exit": result.returncode,
                    "summary": result.stdout.splitlines()[-1:],
                }
            )
            print(name, "detected" if detected else "NOT DETECTED", flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps({"healthy_baseline": "passed", "faults": results}, indent=2) + "\n"
    )
    if not all(row["detected"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
