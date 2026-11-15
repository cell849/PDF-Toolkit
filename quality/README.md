# Focused quality review and reproduction

This review adds development-only checks. No application features or runtime
network/dependency requirements were added. See REVIEW.md for actual results,
TOOL_MATRIX.md for all registered tools and ../benchmarks/REVIEW.md for measurements.
Original files and conversion quality remain requirements, not optimization knobs.

## Linux / development

Install the project in a Python 3.13 environment with `.[dev,media,quality]`.
Provide Poppler's `pdftotext`, `pdftoppm`, `pdfinfo`, `pdfdetach`, plus QPDF and
ExifTool on PATH for independent checks. Optional processing engines are local
LibreOffice, Tesseract with English trained data, and FFmpeg/ffprobe.

```sh
python -m pytest tests -q --timeout=60
python quality/check_fault_detection.py --report quality/results/faults.json
python quality/fuzz_inputs.py --seconds 30 --seed 849 --report quality/results/fuzz.json
mutmut run --max-children 2
mutmut results
python benchmarks/benchmark_suite.py --report quality/results/benchmarks.json
```

Review every skip. Missing readers must not be presented as passed verification.
Mutation testing is deliberately limited to output publication logic; it requires
Linux/WSL and runs no Qt event loop. Never apply mutants to the working source.
If tests changed but cached mutant verdicts did not, rerun named mutants explicitly
or remove only the generated, ignored `mutants/` cache and rerun. Do not chase
wording-only mutations or claim native-library coverage from this result.

The fault runner first checks the healthy source, then copies source into isolated
temporary directories and changes one targeted failure scenario at a time. Test
failure is required; import/collection errors are not accepted as detection.
Fuzz probes are deterministic small mutations of synthetic PDF/PNG seeds, each in
a fresh process with a three-second timeout and monitored 512 MiB RSS limit. RSS
sampling is not a hard OS allocation cap. This is a bounded robustness probe, not
a claim of exhaustive fuzzing or a native-code security sandbox. Failures retain
synthetic repro files under the ignored results directory.

## Windows 11 handoff

Transfer the local source ZIP or Git bundle; nothing needs to be pushed to GitHub.
A bundle can be opened with `git clone LocalPDFToolkit-quality.bundle LocalPDFToolkit`.
Use 64-bit Python 3.13 and an NTFS destination. From the project directory:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,media,quality]"
powershell -ExecutionPolicy Bypass -File .\quality\run_windows.ps1 -Build -RequireOracles
```

Install the independent readers on PATH before `-RequireOracles`: QPDF
(https://qpdf.readthedocs.io/), ExifTool (https://exiftool.org/), and Poppler's CLI
utilities (https://poppler.freedesktop.org/). Without `-RequireOracles` the script
permits missing readers but prints a warning; those test skips remain unverified.
The script checks source tests, runs native process/Qt benchmarks and optionally
builds the portable EXE with its frozen-worker self-test. It does not install
processing engines, upload reports, publish releases or run mutmut on Windows.
Results stay in `quality/results/windows/`.

For a Windows before/after comparison use the same interpreter/dependencies and
hardware. Create a local reference worktree at `791dfef`, copy only
`benchmarks/benchmark_suite.py` into its benchmarks directory, set PYTHONPATH to
that worktree's src, and run the same chosen cases from that worktree. Then unset
PYTHONPATH and run the current source. Keep source/input hashes with each result;
do not compare raw Linux timings to Windows or source timings to frozen timings.

Finish these manual checks with `dist/LocalPDFToolkit/LocalPDFToolkit.exe`:

1. Disconnect networking. Launch, resize, switch tools, preview multiple pages,
   then close; no terminal window or stuck worker should remain.
2. Convert sample PDF/images and merge/split pages; inspect results in a separate
   viewer. Check alpha, orientation and page order.
3. Use Unicode names and a long nested path. If Windows long-path support is
   disabled, require an actionable failure and unchanged originals, not success.
4. Exercise cancel/retry/close during processing and a destination containing
   colliding or locked files. Check originals and unrelated files are untouched.
5. Test missing engines, then locally installed Office/OCR/media engines. Review
   the generated results and disclosures, including raster redaction text loss.
6. Repeat portable-EXE launch/self-test on a clean Windows installation/account
   without development Python. Record build version, skips and observed failures.

A passing offscreen Qt run does not complete these native desktop/clean-machine
checks. Windows results have not been produced in this Linux workspace.
