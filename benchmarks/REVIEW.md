# Targeted performance review

## Idle memory follow-up

On Linux/Python 3.13 with Qt offscreen, five alternating fresh-process samples
before and after deferring PDF-engine imports produced median private memory of
122,396 KiB and 94,004 KiB respectively (23.2% less). Median elapsed startup
was 0.492 s and 0.407 s; these short, warm-cache timings are environment-specific.
The window was opened and its initial events processed; no document was loaded.
The PDF engine is still loaded when needed, so processing memory is not expected
to fall by this amount. Windows and frozen-app memory were not measured. See
`benchmark_idle_memory.py` and `README.md` for the measurement and limitations.

Reference: `791dfefbb3fc7e109dee892afbe090905c4e5404`. Baseline source hashes in
`review-baseline-linux.json` and `review-supplemental-linux.json` match exactly.
After measurements include uncommitted fixes, identified by source hashes in
`review-after-linux.json`. All report input hashes match. See `README.md` for
reproduction and measurement limits.

The 12 MP RGB image path allocated an unnecessary RGBA image, alpha channel and
white background in `images.opaque`, even when the source had no transparency.
The measured baseline peak was 202.6 MiB. Returning an owned RGB conversion for
opaque input preserves ownership and reduces this workload's median sampled RSS
to 142.4 MiB (29.7% lower); measured median elapsed changes from 0.391 s to 0.361 s (7.8% lower).
The timing ranges overlap; this is not a general speed guarantee.
Transparency continues through the existing compositing path. This was the only
performance implementation change proposed by this review.

Literal plain Python startup takes 0.171 s for `import app` (64.2 MiB) and 0.216 s
including `build_registry()` (79.3 MiB). These are seven samples after one warmup.
The first diagnostic `-X importtime` trace attributed 308 ms cumulatively to
QtWidgets, 198 ms to PyMuPDF, 6.4 ms to MainWindow, and 32 ms to pillow-heif during
registry construction. This trace included cold filesystem effects and tracing
overhead; its values must not be added to the warm plain-Python timings. Office
libraries are already imported lazily for conversion. Measured startup does not
justify introducing a new lazy registry or changing multiprocessing architecture.

The original core baseline used harness workers even for startup cases; its
0.202/0.235 s startup numbers include importing this harness and psutil. Use the
supplemental literal Python measurements above for startup. Conversion cases use
the same worker method before/after.

Qt soak: three measured runs plus a discarded warmup, each with 100 real spawned
preview jobs (50 completed, 50 immediately cancelled). Every expected outcome
arrived; no JobController worker remained alive. Each parent retained one Python
resource tracker child. Median elapsed was 25.723 s per 100 jobs. Heartbeat p95
was 5.28–5.30 ms; worst interval across all measured runs was 96.41 ms (other run
maxima 11.24/13.82 ms). Parent RSS first-to-last increased 0.258–0.277 MiB per 100
jobs. This is bounded observed growth, not proof of leak freedom. No GUI/process
implementation changed, so repeating this soak after the image fix was unnecessary.

Optional tools were present and exercised: Tesseract 5.5.0, FFmpeg/ffprobe 7.1.5,
and LibreOfficeDev 26.8.0.0.alpha0. The Office result is a synthetic TXT-to-PDF smoke
workload; the PDF-to-DOCX case exercises the Python Office writer. OCR uses all 20
scanned pages. A development LibreOffice build and synthetic files cannot establish
production document fidelity. The report records exact tool/package versions.

Local dependency inventory: the development virtual environment occupies about
850 MiB (`du -sh`); PySide6 accounts for 644 MiB, PyMuPDF 60 MiB, Pillow 6.7 MiB,
and lxml 12 MiB. The JSON reports list installed versions. These are unpacked Linux
development dependencies, not Windows frozen artifact sizes. PyInstaller already
uses an onedir build and a subprocess self-test. Any package exclusion must be
validated on a real Windows build; no unsupported release-size claim is made.

Conversion and preview work runs in spawned workers; Qt retains polling and
display work on the UI thread.
Preview intentionally snapshots and hashes the whole source on each page request;
this is additional work for large files but enforces a consistent input for preview
and redaction. Retain that correctness property in any future caching proposal.
Page rasters are processed one at a time; observed PDF100 RSS stays near 71 MiB.

Linux measurements do not cover Windows GUI responsiveness, frozen startup,
codec distribution/licensing, or clean-machine packaging. Benchmark outputs use
synthetic input only and contain no document metadata values or personal paths.

| Workload | Baseline s (range) | After s (range) | Baseline / after RSS MiB |
| --- | --- | --- | --- |
| text100 | 9.220 (9.201–9.719) | 9.246 (9.151–9.632) | 71.0 / 71.0 |
| scan20 | 1.544 (1.533–1.578) | 1.496 (1.473–1.608) | 76.3 / 76.5 |
| image12mp | 0.391 (0.389–0.544) | 0.361 (0.330–0.637) | 202.6 / 142.4 |
| pdf_docx | 1.572 (1.500–1.612) | Not repeated | 68.0 / — |
| office_pdf | 0.508 (0.501–0.681) | Not repeated | 177.1 / — |
| media | 0.448 (0.436–0.473) | Not repeated | 80.5 / — |
| ocr | 37.378 (35.761–38.601) | Not repeated | 119.5 / — |

All comparable median elapsed changes stay below the 10% regression threshold;
all comparable median sampled RSS changes stay below the 15% threshold. Office,
media and OCR converters had no performance changes and were not repeated; no
before/after performance claim is made for these paths. Output counts and byte sizes match
before/after for all three repeated cases. Samples, environment and source hashes
are preserved in the JSON reports.
