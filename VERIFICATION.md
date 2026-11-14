# M0 verification — 2026-11-11

Environment: Linux x86-64, CPython 3.13.5, PySide6 6.8.3, Qt offscreen.
Windows 11 is the target; no Windows execution has been performed here.

Results:

- `python -m ruff check .`: passed.
- `python -m ruff format --check .`: passed (15 Python files).
- `python -m pytest`: 17 passed. Includes registry discovery of a test-only
  converter, invalid/duplicate capabilities, cancellation, progress, synthetic
  fixture integrity, and Qt window creation, discovery and closure.
- `python -m build --installer uv`: source distribution and wheel built.
- Installed the wheel into a separate Python 3.13 environment and invoked its
  actual entry function from outside the repository. A timer observed the
  visible window, captured it, and closed it; exit status was zero. The imported
  module was verified to come from that environment's site-packages.
- Visually inspected the offscreen window capture: title, empty operation state,
  and foundation status were displayed correctly.

The initial `python -m build` attempt failed because this Linux Python lacks
ensurepip. Using build's `--installer uv` option resolved that without system
changes. The normal pip-based build command is retained for a standard Windows
Python installation. uv's cache was placed under the workspace because the
cloud user's default home cache is read-only.

Remaining validation: launch on a real Windows 11 desktop and run the configured
Windows CI job. No conversion fidelity, throughput, output safety or packaging
as a standalone Windows executable has been claimed; those belong to later
milestones. There is no production conversion adapter in this milestone.


# M1 verification — 2026-11-11

Environment: Linux x86-64, CPython 3.13.5, PySide6 6.8.3, PyMuPDF 1.26.7.
Qt tests use its offscreen platform. Actual Windows 11 validation remains pending.

- `python -m pytest`: 53 passed, including all M0 checks.
- `python -m ruff check .` and `python -m ruff format --check .`: passed.
- `python -m build --installer uv`: source distribution and wheel built.
- Rendering tests check JPEG/PNG dimensions at all three DPIs, source hashes,
  page selection, transparency, scanned/rotated content and 100-page completion.
- Failure tests cover invalid options/ranges, corrupt and encrypted inputs,
  pixel guardrails, existing outputs, a concurrent publication collision,
  simulated write permission denial, and cancellation cleanup.
- Qt/process integration covers real spawned conversion, GUI timer responsiveness,
  cancellation, recovery after a failed PDF, local file drop, window conversion
  and cooperative cancellation on close.

No performance improvement or throughput claim is made; the 100-page test is a
correctness check, not a benchmark. Limits and hard-link filesystem requirements
are documented in README.md. Cancellation cannot interrupt an individual native
parse/render/encode call. No standalone Windows installer has been produced.

Installed-wheel smoke check also passed: from outside the repository, the real
application opened with both operations, converted the synthetic fixture through
the UI and spawned worker, and produced a 1275 x 1650 JPEG at 150 DPI. The
completed-window screenshot was visually inspected. Import location was checked
to confirm execution from the separate environment's installed wheel.

# M2, M3 and M5 expansion; M4 preparation — 2026-11-11

Two independent Sol subagents implemented PDF tools and Office adapters under
AGENTS.md's delegation policy. The main agent reviewed and integrated their code,
registered all 28 operations, implemented images/compression/queue controls, and
ran integrated checks. No main-agent model switch is claimed.

- Full integrated suite: **135 passed in 38.04 seconds**. Subsequently added a
  queued-job cancellation regression; the queue subset was **3 passed**. Thus
  136 distinct tests have passed across the full run and focused follow-up.
- Ruff check and format check pass (33 Python files). Git whitespace check passes.
- M5's focused 28-test suite exercised all nine advertised forward formats through
  real LibreOffice, plus DOCX/XLSX/PPTX reverse parsers and safety/error handling.
  Engine: bundled LibreOfficeDev 26.8.0.0.alpha0, not a production Windows release.
  No LibreOffice was installed by the agents.
- All registry option forms were constructed and checked against their declared
  defaults. Compression UI screenshot was visually inspected.
- Source distribution and wheel built with `python -m build --installer uv`.
- A Linux PyInstaller onedir executable built and passed `--self-test`, which
  converts through an actual spawned child inside the frozen application.
- Windows PowerShell build script and manually triggered GitHub Actions workflow
  are supplied. **No Windows executable was built or tested here.** No CI run,
  installer, code signature or clean-Windows verification is claimed.

Reproducible benchmark: benchmarks/baseline-linux.json records a generated
100-page PDF at 150 DPI/quality 85. First/repeat wall times were 6.662/7.965 seconds;
sampled peak worker RSS was 66.76/66.89 MiB; each run produced 100 images.
Sampling interval was 20 ms, process startup is included, OS caches were not
flushed. This is a baseline on this Linux host, not an optimization claim or a
Windows performance guarantee.

The user's uploaded s.pdf was used only as data and not committed as a fixture.
It has one unusually large page (about 2599 x 3677 PDF points). Its 150-DPI render
was correctly rejected by the 40-million-pixel guardrail; 72-DPI PNG succeeded.
An image-to-PDF round trip succeeded. Image compression under a 200 KiB limit
produced 110216 bytes; rasterized PDF compression under a 1 MiB limit produced
1020411 bytes. The input SHA256 remained unchanged. PDF/image compression trials
were bounded and oversized results were not published. No contents were logged.

Known limits and intentionally deferred screenshot tools are in CAPABILITIES.md.
M4's actual Windows build and clean-machine verification remain outstanding.

## Windows packaging handoff correction

A subsequent packaging review found that the manual Actions workflow installed
packages globally while build_windows.ps1 requires `.venv/Scripts/python.exe`.
The workflow now creates and uses that environment for installation, lint,
formatting and tests before packaging. The script verifies 64-bit Python 3.13,
and its packaged-worker check now has a 60-second process-tree timeout. Actions
also has a 20-minute job limit.

Validation for this configuration-only change: both workflow YAML files parsed
successfully with PyYAML; `git diff --check` passed. No Windows or PowerShell
execution is claimed. The full application test suite was not repeated for
this packaging configuration change. Actual Windows build, package launch and
clean-machine verification remain pending a Windows execution target.


# GitHub Windows build verification — 2026-11-15

Repository: https://github.com/cell849/tools (private).
Verified application commit: 68a3bb29ee52f6689252650127f8f32f65463969.
Checks: https://github.com/cell849/tools/actions/runs/43655035831
Package: https://github.com/cell849/tools/actions/runs/43655035967
Artifact: https://github.com/cell849/tools/actions/runs/43655035967/artifacts/14136709874

Both Windows and Ubuntu CI passed lint, format, and **128 tests, 9 skipped**.
The nine real-LibreOffice conversions were skipped because those runners lack
LibreOffice; earlier real-engine cloud results still apply only to that engine.
The Windows PyInstaller build and the frozen executable's spawned-worker JPEG
conversion self-test passed. The 83,412,107-byte Actions artifact contains the
portable Windows ZIP. No installer, signing, public release, or clean Windows 11
manual desktop/Office validation is claimed.

Windows CI exposed and led to fixing a real controller bug: a closed Windows
named pipe raises BrokenPipeError from poll(), unlike POSIX EOF handling. The
controller now treats both as stream completion, with a regression test. Office
tests were corrected to distinguish taskkill's process from the controlled child
and to decode Windows file URIs with url2pathname. Linux CI now installs Qt's
required EGL/OpenGL runtime libraries. Test runs have per-test and step timeouts.

This section supersedes earlier statements that no Windows binary was built.
Manual Windows 11 desktop testing and the optional final independent review
remain outstanding. No uploaded user document was committed to the repository.
