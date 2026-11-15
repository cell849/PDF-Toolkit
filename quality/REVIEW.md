# Targeted correctness, stability and performance review

Reference: `791dfef`. Scope: existing 40 tools, unchanged functionality and GUI;
local commits only. No push, release, cloud processing or private fixture upload.
The work used two bounded independent agents: integrity checks and performance
measurement; the main agent reproduced/fixed defects and integrated evidence.

## Confirmed findings and fixes

| Priority | Reproduction before fix | Resulting correction |
| --- | --- | --- |
| P1 | A 20,000,000 × 1 pt PDF page requested 55,555,556 pixels; a 10,000,000 × 2 pt page requested 41,666,667 despite a 40 MP limit. Tests intercepted allocation safely and failed before repair. | Compression now checks the product of rounded raster dimensions and reduces DPI until it is safe; very large pages can still fail explicitly. |
| P2 | Injecting PermissionError on the first rollback destination prevented deletion of two later removable outputs. Regression failed before repair. | Cleanup continues independently, preserves foreign replacements and propagates locked-output errors after attempting remaining cleanup. An OS-locked file can still remain and needs user attention. |
| Performance | An opaque 12 MP image unnecessarily used RGBA, alpha and background buffers. | Direct owned RGB conversion for sources without alpha/transparency. Alpha sources retain the original compositing path. |

The performance change reduces median sampled process-tree RSS from 202.6 to
142.4 MiB (29.7%). Image median elapsed changed 0.391 to 0.361 s; ranges overlap,
so this is an observed timing change, not a general speed guarantee. No comparable
PDF workload exceeded the 10% elapsed or 15% memory regression thresholds. No lazy
registry rewrite or blanket DLL/dependency stripping was justified by measurement.
The development venv size is not a Windows portable package-size measurement.
See ../benchmarks/REVIEW.md and its raw environment/source/input-hash reports.

## Verification evidence

- Existing baseline: 348 tests passed in the previous implementation run.
- 40 new integrity cases use independently authored raw PDFs and Office ZIP/XML,
  genuine original hashes, real concurrent publishers, injected filesystem
  faults and Poppler/QPDF/ExifTool result checks. All 40 passed without skips.
- 11 property/unit cases include generated page selections, collision positions,
  cancellation boundaries, cross-volume staging and locked-output reporting.
- Six deliberately broken source copies were all detected after a healthy
  baseline: overwrite existing files, ignore cancellation, retain image metadata,
  redact the wrong page, ignore source digest, ignore the raster pixel budget.
  See fault-detection-linux.json.
- mutmut 3.8.1: 47 publication-logic mutants; 32 killed, 15 reviewed survivors. Survivors
  change diagnostic wording, temporary-directory naming, or strict resolution
  of already invalid destinations; none leaves an unclassified integrity gap.
  No blanket mutation score or native-library claim is made. Mutation feedback
  added separate-volume publication and locked-cleanup exception checks.
- Deterministic seed 849 parser probe: 218 small PDF/PNG mutations in 30.04 s,
  24 accepted and 194 cleanly rejected, with no unexpected exits, timeouts, source
  changes or sampled memory-limit violations. See fuzz-linux.json.
- Four 100-cycle Qt runs (one warmup plus three measured) completed all expected
  preview/cancellation outcomes; no active worker remained. Parent RSS growth
  was below 0.28 MiB/100 jobs; worst measured heartbeat gap 96.4 ms.

Final full suite: **399 passed in 89.05 s**, with independent readers present and no skips.
Ruff lint/format and diff whitespace checks are also required before commit.

## Limits and remaining verification

All current evidence is Linux/source execution. The Windows handoff is prepared
in README.md and run_windows.ps1; native Windows filesystem/GUI, frozen package,
DLL discovery and clean-machine checks are explicitly not yet verified. No
Windows EXE or download has been published. Optional readers/engines must be
present for corresponding future tests to count as verified.

Inputs are bounded and synthetic. Cross-engine pixels compare stable interiors,
not identical font anti-aliasing. This does not establish fidelity for every real
Office document, every codec, every malformed file or every native-library bug.
No general anonymity, crash-sandbox or leak-freedom guarantee is inferred.
