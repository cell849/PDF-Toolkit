# Comparison, normalization and recovery

The new tools extend the existing registry, worker and preview paths without runtime
dependencies. Image comparison loads one source and saves JPEG/PNG/WebP candidates
at identical dimensions, clearing metadata and compositing JPEG onto white.
Compare selects each candidate with exact saved sizes. All candidates are saved;
this is not a perceptual quality estimator.

Normalize page sizes supports DIN A/B/C 0–10 and custom mm/cm/in/pt dimensions,
per-page auto orientation, selected ranges, margins, contain and centered cover.
Rebuilt selected pages retain vectors/text with baked annotation/form appearance;
interactivity is lost. Crop-box/rotation rendering regressions are included.
Unselected pages remain copies, including internal page navigation where possible.
Bookmarks/attachments/document signatures are not promised. Cover is not redaction.

Recovery records live in per-user app state only while jobs are active/interrupted.
File locks, directory identity and markers protect active/unfamiliar files. Cleanup
is opt-in from Tools and preserves every published output. Tests include abrupt
process death/restart, partial publication, active processes, corrupt records,
symlinks, changed records and locked-file retry. Unknown legacy leftovers are not
swept; nested or unsafe contents require manual review. Persisted paths are necessary
for recovery and are disclosed in CAPABILITIES.md. No automatic reprocessing occurs.

UI follows the installed Apple design skill's disclosure-controls.md, Best practices:
“Use a disclosure control to hide details until they’re relevant.” Custom dimensions
appear only for Custom paper. The existing Windows comparison and confirmation
controls remain; no effects or new UI dependencies were introduced.

Verification: integrated Linux suite 668 passed; final normalization rerun 81
passed and final workspace rerun 18 passed after the last link/compare additions.
Lint/format/whitespace checks passed. Windows artifacts run the full current suite,
native workflows at 150% scale, frozen EXE and self-signature/tamper checks.
