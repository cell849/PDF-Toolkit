# Local PDF Toolkit — Project Blueprint

Status: M0–M3 and M5 implemented in Linux; M4 packaging/Windows verification tracked below.
Target: Windows 11-first, personal-use, completely local desktop application.
Priority: Balanced speed, conversion quality, maintainability, and reasonable AI development cost.

## Product contract

- All document processing occurs on the user's computer. No upload, account, telemetry, or AI API is required to convert files.
- Input files are not modified. Outputs are written to a user-chosen directory, via temporary files and atomic finalization where supported.
- The UI stays responsive while jobs are running, and displays per-job status, progress where measurable, errors, and cancellation.
- A converter must declare exactly which input/output pairs and options it supports. Unsupported or potentially lossy operations are labeled honestly.
- Support Windows first; avoid unnecessary platform-specific logic in the conversion layer.
- Distribution is personal use at first. Revisit redistribution rights and package licenses before sharing any installer.

## Technical choice

**Initial stack: Python 3.13-compatible application, PySide6 UI, PyMuPDF PDF rendering and manipulation, Pillow for basic images, pytest.**

Rationale: Native conversion libraries do the compute-heavy work; Python speeds up orchestration and iteration. This is lower-complexity than a Tauri + Rust frontend/backend combination for a Windows-first personal app. Use tested compatible versions rather than automatically upgrading to the latest releases.

Potential later adapters:

- `qpdf`: structural PDF operations that benefit from a dedicated CLI.
- `libvips`: high-throughput or low-memory image processing once benchmarks show Pillow is a bottleneck.
- `LibreOffice`: optional, locally installed headless engine for Office to PDF.
- `OCRmyPDF` / Tesseract: searchable scanned PDFs in a later phase.

PyMuPDF is AGPL/commercial dual-licensed. Its use should be reviewed before distributing the app. Other adapters have their own licenses, native dependencies, and packaging considerations.

### Internal modules

```text
local-pdf-toolkit/
  pyproject.toml
  README.md
  AGENTS.md
  PROJECT_PLAN.md
  FEATURES.md
  src/local_pdf_toolkit/
    app.py                 # application entry point
    ui/                    # drag/drop, options, queue, dialogs
    core/
      formats.py           # verified file type + support matrix
      contracts.py         # converter and job interfaces
      registry.py          # supported operations and adapter lookup
      jobs.py              # bounded job execution, cancellation, status
      output.py            # paths, temp files, naming, cleanup
      errors.py            # user-facing and diagnostic errors
    converters/
      pdf_images.py        # PDF pages to JPEG/PNG
      images_pdf.py        # images to PDF
      pdf_pages.py         # merge/split/extract PDF pages
      office_pdf.py        # optional later adapter
  tests/
    fixtures/
    test_pdf_images.py
    test_images_pdf.py
    test_pdf_pages.py
    test_jobs.py
    test_output.py
  benchmarks/
    benchmark_pdf_images.py
```

### Conversion contract

Each converter exposes:

- A stable operation ID (e.g. `pdf.to_jpeg`).
- Accepted input formats and one or more output formats.
- Option definitions, defaults, and validation rules.
- Input verification (not extension-only).
- `convert(input_path, output_dir, options, progress, cancel_token) -> output_paths`.
- Structured errors; no silent partial success.

The UI queries the registry to present available operations and their options. It must not hard-code conversion rules. Registry entries are maintained as code, not executable third-party plugins supplied by arbitrary files.

### Job model

Use a queue with bounded concurrent workers. Keep the Qt main/UI thread free of conversion work. Start with one heavy conversion at a time and allow configurable concurrency after measurements; too much parallel rendering can exhaust RAM. Separate job metadata from actual input/output files. Never pass an open PDF/document instance between processes. A cancellation request should stop future pages promptly and safely discard temporary outputs. Report progress as `completed pages / total pages` where known; otherwise use an indeterminate state.

### PDF to JPEG behavior (first vertical slice)

1. User drags one or more PDFs into the app.
2. The registry selects `pdf.to_jpeg` and displays output directory, page range, resolution, and JPEG quality.
3. Worker validates the PDF, opens it, and renders pages individually at the selected DPI.
4. Each JPEG is written to a temporary output and finalized only after successful encoding.
5. The UI receives progress, cancellation, result paths, and actionable errors.
6. Output names are deterministic: `<source-stem>_page-0001.jpg`, etc. Collision handling must not overwrite an existing file without consent.

Initial options: pages = all or explicit range; DPI = 72/150/300; quality = 85 by default; RGB; JPEG has no transparency. Always explain that PDF to image rasterizes text and vector content.

### Security and correctness

- Treat files as untrusted. Validate signatures and confirm with parsers; reject unsupported, corrupted, or password-protected files with clear messages.
- Do not execute embedded macros or document scripts. Never interpolate filenames into shell command strings. Use subprocess argument lists for optional CLIs.
- Do not follow uncontrolled output paths; normalize names and stay inside the selected output directory.
- Use size/page-count guardrails, timeouts for external processes, and bounded concurrency to mitigate resource exhaustion.
- Preserve original files, remove incomplete temporary outputs, and keep logs local without logging document contents.
- Do not promise a security sandbox until one is actually implemented and tested.

## Quality and benchmark gates

Build fixture coverage for: one-page PDFs, 100-page PDFs, mixed page sizes and orientations, transparent content, scanned pages, non-ASCII filenames, corrupt files, encrypted PDFs, name collisions, cancellation, and output-directory permission failures.

For visual fidelity, compare page dimensions and inspect representative rendered images. Avoid brittle byte-for-byte JPEG comparisons. Track:

- Wall-clock runtime (cold and warm) for fixed local test documents.
- Peak resident memory.
- Output file count and dimensions.
- Conversion success/failure and cleanup correctness.
- UI responsiveness during conversion.

Do not claim an optimization improved speed without before/after measurements on the same input and machine.

## Milestones

### M0 — Foundation and decisions

Implementation note (2026-11-11): Windows 11 and the working name Local PDF
Toolkit are confirmed. The repository, Python 3.13 environment, converter
contracts, empty production registry, minimal Qt window, synthetic fixture,
tests, and CI workflow are implemented. Linux offscreen window and automated
checks are verified; actual Windows desktop verification is still pending.
Personal use is confirmed; a distribution license has not been selected.

- Confirm Windows version, project name, license approach, output behavior, and distribution expectations.
- Initialize repository, virtual environment, formatting/linting, pytest, CI-ready commands, and fixtures.
- Implement contracts and the converter registry without unnecessary extension frameworks.
- **Done when:** tests run, the registry can list a test converter, and the app launches an empty window.

### M1 — Complete PDF to JPEG/PNG vertical slice

Implementation note (2026-11-11): JPEG/PNG rendering, registry-driven options,
file import/drop, sequential spawned workers, progress, cooperative cancellation,
safe staging/publication and structured errors are implemented. Synthetic
rendering and Qt/process integration tests run in Linux; actual Windows 11
desktop and filesystem verification remain pending. Output directories must
support hard links (local NTFS recommended).

- Drag-and-drop PDF, options, progress, output selection, cancellation, and error handling.
- Add explicit page-range validation and safe naming.
- **Done when:** representative PDFs convert correctly at selected DPI, originals remain unchanged, and automated checks pass.

### M2 — Core PDF and image tools

- JPEG/PNG to PDF (one image per page; multi-image PDF).
- Merge, split, and extract PDF pages, with ordering controls.
- **Done when:** all P0 conversions have fixtures and predictable output behavior.

### M3 — Batch queue and performance

- Multiple queued jobs, batch options, error isolation, cancel/retry, user-readable results.
- Establish benchmark baselines and optimize measured bottlenecks.
- **Done when:** a 100-page PDF and a multi-file batch complete with bounded RAM and no UI freeze.

### M4 — Windows packaging and operational polish

- Build a local Windows package, handle missing native dependencies and errors, provide offline verification instructions.
- Add safe update/manual install guidance; no telemetry or automatic network requests.
- **Done when:** the app works on a clean Windows test environment with documented requirements.

### M5 — Optional Office conversion

- Assess whether the user actually needs DOCX/XLSX/PPTX to PDF.
- If approved, add LibreOffice as an optional adapter with dependency detection and documented fidelity limits.
- **Done when:** accepted Office fixtures convert locally, and failures are clearly reported.

## Scope and change control

- Keep all features in `FEATURES.md` with priority and acceptance criteria.
- Implement only the approved milestone. New features first become proposals, not silent additions.
- Prefer the smallest production-quality change that meets acceptance criteria.
- Revisit architecture only with evidence: measured bottleneck, repeated duplication, or a blocking requirement.

## Initial development command

"Implement M0 only. Use the model-routing and delegation rules in AGENTS.md. Create a Windows-first PySide6 project skeleton with converter contracts, registry, a minimal launchable window, fixtures, and tests. Do not add conversion features or optional dependencies until M0 acceptance criteria are met."

## Authorized roadmap update — 2026-11-11

The user requested autonomous continuation and broad non-AI local capabilities.
Execution order is **M2, M3, M5, then M4**. Feature expansion and fidelity limits
are tracked in FEATURES.md and CAPABILITIES.md. M5 no longer needs a separate
approval. M4 may prepare Windows packaging here, but actual Windows builds and
clean-Windows verification require a Windows runner; Linux checks do not satisfy
that platform gate.

M2 implements ordered multi-input contracts, images to PDF, structural PDF tools
and the additional adapters in CAPABILITIES.md. M3 adds queue ordering, failure
isolation, job/all cancellation, retry and reproducible sampled-RSS/runtime
baselines. M5 adds optional installed LibreOffice and limited reverse Office
exports; its real-engine tests precede M4 packaging work.

M4 preparation result: Windows build script/manual workflow and portable-folder
instructions are supplied; the Linux frozen-build worker smoke test passed.
Actual Windows executable generation and clean-Windows verification are pending.
See VERIFICATION.md for measured results, not just planned acceptance gates.
