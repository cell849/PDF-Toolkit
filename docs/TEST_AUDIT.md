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
