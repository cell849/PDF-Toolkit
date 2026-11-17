# Test scope for 0.7.2

Removed the M0 fixture byte-layout check: real PDF parsing/rendering and independent
readers already exercise that fixture. Removed the single-converter window-discovery
test and merged operation count/label checks into the existing all-options smoke test.
Removed checks for a specific Qt style name, popup widget class and QIcon class.
The dropdown now exercises keyboard selection and deliberate wheel behavior instead.

Retained atomic output/no-overwrite, source preservation, metadata removal,
independent format readers, cancellation, worker shutdown, compression bounds and
visible card/layout regressions. Similar-looking format/error cases often target
different parsers, options or failure boundaries; they are not removed by count.

New tests cover actual batch naming/copy publication and document inspection,
including UI-to-worker flows and a grouped Retry that must retain the full name plan.
No tests were added solely to mirror scrollbar CSS. Both scrollbar orientations were
visually reviewed and manually checked with keyboard scrolling and arrow geometry
in light and dark themes.

For small changes, run the affected module tests locally; run the full suite before
releasing. Basic CI skips unavailable optional engines explicitly; the Windows
release job installs them and gates publication on the full suite and a frozen EXE
self-test. Development tests are outside the application source package and do not
run during normal app use. Test cleanup does not imply faster document conversion.

## Focused development checks

Use `python scripts/check.py --files <changed paths>` for a quiet affected-test run,
`--plan` to inspect selection, and `--full` for the complete gate. With no paths it
uses modified/untracked files. Python import dependencies select converter tests;
shared/core/UI/packaging changes and unknown source changes fall back to the full
suite. Dynamic/plugin imports cannot be proved by static analysis: use --full when
in doubt. Full Windows packaging tests remain mandatory. Logs stay in ignored
.check-results.log; only summary/failure excerpts need to enter assistant context.
CI uses quiet pytest output while retaining skip reasons and failure details.

Removed 30 repetitive paper-size conversion cases: their expectations reused the
implementation's own size table. The replacement checks DIN table completeness and
halving relationships, plus six actual conversions with independent expected values
covering families, extremes and US sizes. Rotation/crop rendering, custom units,
links, safety and error-boundary regressions remain. This reduces duplication rather
than changing acceptance criteria or hiding failures.
