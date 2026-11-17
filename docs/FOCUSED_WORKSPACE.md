# Focused workspace follow-up

Approved scope: category-first home, improved comparison viewer, batch outcomes,
lean checks, visual page organization and PDF comparison. No runtime dependencies.

## Behavior

- Home opens to seven categories and search; Browse all tools retains all tools.
  Search/category selection opens the grid, and Home resets discovery filters.
- Batch status filters retain original list indices. Retry still targets failed
  inputs; selecting a saved/failed row shows its outcome without replacing the
  batch failure banner. Clear resets cancellation/error state for new inputs.
- Comparison has Fit, 100% preview-pixel zoom, linked pan/Ctrl-wheel zoom and an
  opt-out. Large images remain bounded previews; no original-pixel claim is made.
- Visual organizer supports multi-selection, drag/keyboard reorder, rotate,
  remove, insert and undo. All previews/reads are worker jobs. Output uses verified
  source snapshots bound to the reviewed digest. One thumbnail worker and 32-icon
  cache prevent raster memory from growing with page count. Shared placeholders
  keep label positions stable before loading. Cells grow with enlarged text.
- PDF comparison exports a highlighted PDF and text report by corresponding page
  number. Explicit resolution/tolerance/text bounds prevent false semantic or
  forensic guarantees. The text report is kept out of image preview choices.
- Developer checks select imported dependencies for converter changes, default to
  the full gate for shared/unknown changes, log quietly and keep full release tests.
  See TEST_AUDIT.md for the actual redundancy removed and usage.

## Verification

Full integrated Linux gate: 678 passed in117s. Final comparison/organizer/workspace
rerun:55 passed; final organizer placeholder refinement:24 passed. Lint/format and
whitespace checks passed. Real workflows verify snapshot-bound ordered export,
selected-result/report mapping, filtered Retry, worker close and lazy thumbnails.
Rendered home light/dark, regular/compact organizer and generated highlight report
were inspected in Linux. Windows native UI and self-signed package gates are run
separately; these do not replace human screen-reader/display/drag usability testing.

Representative checks were reduced without relaxing their contracts: thirty
repeated size-table conversions were replaced by independent boundary/family/US
conversions and table consistency. Substantial parser/lifecycle safety checks remain.
Test count is not used as a quality measure; normal usage never runs the suite.

## Design reasoning

Installed Apple skill references consulted: layout.md, Visual hierarchy says
“Use progressive disclosure to make layouts cleaner and easier to interact with.”
The category-first home and contextual batch filters follow that principle.
sidebars, zoom and keyboard controls retain Windows conventions. Stable thumbnail
cells and concise task wording are practical usability choices; no glass effects,
custom window controls or claim of full Apple-platform compliance was introduced.

## Limits

Organizer exports vector/text pages with baked annotation/form appearances; links,
interactive forms, document signatures/bookmarks/attachments and advanced document
features are not retained. User originals never change. Source file lists/order and
thumbnail arrangement are separate: the reviewed grid defines output order.

PDF comparison is bounded raster plus extracted-text comparison: no alignment of
inserted/reordered pages, OCR, semantic interpretation or signature validation.
Small visual details can be missed, and text excerpts can truncate; output states
these limits. Reports can contain private visible text, unlike the masked metadata
inspector. Saved difference reports are previews of changes, not redacted documents.
