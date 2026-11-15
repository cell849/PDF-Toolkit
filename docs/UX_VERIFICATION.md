# 0.7.0 workspace verification

The user approved the complete document-workspace and UX changes after reviewing
the proposals. Existing conversion capabilities and offline processing remain.
No new runtime dependencies were added. New UI artwork is original SVG/PNG/ICO;
Windows retains its native window frame.

## Implemented behaviours

- Three-pane workspace and compact options toggle; target amount/unit controls
  stack when needed rather than clipping or requiring horizontal scrolling.
- Persistent success/partial/error/cancelled banner and contextual recovery.
- Content-verified inspection in a worker, compatible tool carryover, session-only
  document/settings context, clipboard/drop and compatible-tool suggestions on
  home-screen drop. No processing starts merely from dropping a file.
- Embedded Original/Result preview, result-first on success, bounded cache,
  transparency, zoom/page controls, stable matching-geometry view and stale notices.
- Small file icons retain only 48 px thumbnails, not full 1400 px preview rasters.
- Output naming uses staging/atomic publication, correct extensions and no overwrite.
  Undo of remove/reorder preserves other results. Reordering combined inputs marks
  earlier results stale. Retrying uses corrected settings and keeps other successes.
- Clear available/missing engine information, contextual help and settings summary,
  disabled inapplicable lossless-DPI settings, larger text and system appearance.
- Only window/pane sizes, preferred units and text size persist. Document paths,
  contents, output names and tool settings are session-only.

## Checks

A complete Linux run passed 523 tests with all independent readers present and no
skips. A subsequent bounded-thumbnail regression plus its workspace suite passed
12 tests. Final Windows checks run on the release source commit and remain the
native release gate. Targeted worker/startup tests passed after moving GUI-only
imports into the GUI launch path.

The first complete run during implementation also passed 520 tests; further tests
cover accidental scrolling, keyboard movement beyond slider landmarks, home-screen
drop suggestions and thumbnail memory. Earlier state-review failures were fixed,
not excluded: preflight cancellation/close, named reports, bulk names with a typed
extension, cancelled-vs-failed summaries, encrypted PDF unlocking and rejected Retry
state leaking across tools. Compact layouts are checked at 760×620; synthetic
end-to-end screenshots were reviewed at 1380×900 and 760×720, light/dark and 150% text.
This is automated/engineering review, not an independent first-time-user study.

Seven measured startup samples after one warmup: plain import median 0.106 s and
registry-building median 0.159 s on this Linux environment. These are import/registry
measurements, not first-window or Windows launch timings. Before moving GUI imports,
the same current-source cases measured 0.203/0.243 s. The change also avoids importing
the UI in conversion worker startup. No conversion-throughput speedup is claimed.

Source/wheel builds succeeded with the pinned build backend; the wheel includes
all seven icon assets. The packaging self-test now uses QApplication, renders the
workspace, verifies icon/SVG availability and checks a real spawned conversion.
A final checksum accompanies the Windows ZIP. Signing is optional but strictly
verified when requested; no trusted signing identity was provided for this release.
SmartScreen warnings remain possible. No security policy is bypassed.
