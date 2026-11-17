# Reproducible offline performance review

For Linux idle-window memory, run the following in several fresh processes with
no other copy of the app running (shared pages affect private-memory readings):

```sh
QT_QPA_PLATFORM=offscreen python benchmarks/benchmark_idle_memory.py
```

The script opens the window, processes its initial events and reads Linux
`/proc/self/smaps_rollup`. It reports RSS, proportional and private pages in KiB,
plus elapsed startup time. It measures an offscreen development environment,
not a frozen Windows build or memory consumed during document processing.

Use the project's Python environment with the development dependencies installed:

```sh
python benchmarks/benchmark_suite.py --report benchmarks/review-local.json
```

Default: one discarded warmup, seven measured fresh processes per normal case and
three per heavy case. `--quick` uses one sample, no warmup and ten soak jobs; use
it only to check the harness. Select cases with `--cases import_app image12mp`,
or configure `--runs`, `--heavy-runs`, `--warmup`, `--soak-jobs`, and `--timeout`.
Run without other CPU/memory intensive tasks. No network or real documents are used.

| Case | Synthetic input and operation |
| --- | --- |
| `import_app` | Literal fresh `python -c 'import local_pdf_toolkit.app'` |
| `build_registry` | Literal fresh Python import plus `build_registry()` |
| `text100` | 100 A4 text pages, JPEG export at 150 DPI |
| `scan20` | 20 A4 image pages, JPEG export at 150 DPI |
| `image12mp` | Deterministic 4000×3000 RGB PNG, JPEG export |
| `pdf_docx` | 100 text pages, selectable-text DOCX export |
| `office_pdf` | 100-line TXT document, local LibreOffice PDF export |
| `ocr` | 20 scanned pages, local Tesseract English OCR at 150 DPI |
| `media` | One-second mono PCM WAV, local FFmpeg metadata reconstruction |
| `qt_soak` | 100 sequential spawned preview jobs; alternating completion/immediate cancellation |

Reports include every sample, medians and ranges, synthetic input sizes/hashes,
source/harness hashes, revision, package versions, executable versions, CPU count
and platform. Missing optional executables are explicitly skipped. There are no
source document paths or contents, personal metadata, hostnames, or environment
variables in reports. Reports contain synthetic fixture filenames and repository
relative source paths. Worker failure is fatal; successful cases are checkpointed.

Elapsed time includes interpreter startup/shutdown. Conversion workers import this
harness and psutil; literal startup cases do not. RSS samples every 10 ms sum each
worker and all observed descendants, including LibreOffice/Tesseract/FFmpeg. Shared
pages can be counted more than once and short peaks can be missed. This is process
tree RSS, not private memory, an OS high-water mark, or whole-machine consumption.
Startup profiling with `-X importtime` is diagnostic only; its tracing overhead is
not comparable with plain elapsed time. Warm filesystem caches are not flushed.

Qt uses the offscreen platform. A 5 ms timer measures event-loop heartbeat gaps
during the actual JobController start, completion and cancellation flow. It records
p95/max intervals, first/last parent RSS, and remaining children. Python's persistent
multiprocessing resource tracker can remain as one child after all jobs finish.
This exercises real spawned workers and temporary output cleanup; it does not
replace interactive Windows testing or prove absence of every memory leak.

`benchmark_pdf_images.py` and `baseline-linux.json` are the original two-sample
benchmark. Their less dense input and measurement scheme differ; do not compare
their absolute times with the newer suite.

For a focused batch-copy/parsing diagnostic, run:

```sh
python benchmarks/benchmark_file_tools.py benchmarks/v08-file-tools-linux.json
```

This compares a 1 MiB chunk copy, file inspection and batch rename copies on one
synthetic 4096×4096 RGB BMP (48 MiB). Three fresh subprocesses run each operation.
Operation time excludes startup/imports; sampled RSS includes them. Inspection
copies a snapshot before parsing, and batch rename first stages its own copy.
This identifies copy versus decoding costs on that fixture; it does not establish
performance for compressed images, PDFs, Office files or slower output devices.
