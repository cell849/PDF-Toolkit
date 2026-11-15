# Visual polish after 0.7.2

The focus is a quieter document workspace: fewer competing headings and controls,
while keeping all 42 tools and their options available. Changes are confined to
the Qt presentation layer; no runtime dependencies or conversion features were
added or removed.

## Changes

- Simplified library heading, sidebar copy, format badges and typography.
- Aligned card content with explicit spacing and measured wrapping heights.
- Grouped the Tools menu using the same categories as the sidebar.
- Hid idle progress and cancellation controls, and duplicate result text.
  Unique status messages and persistent error/recovery banners remain visible.
- Gave the empty preview a quiet placeholder. Page, zoom and comparison controls
  appear when a document is selected. Preview backgrounds follow the palette.
- Retained search, keyboard shortcuts, accessible names, text scaling, all option
  forms and the existing compact layout.

The Apple design skill's `references/hig/layout.md`, **Visual hierarchy**, says
“Group related items to clearly express related information or functions” and
“Use progressive disclosure to make layouts cleaner and easier to interact with.”
These inform the grouped menu and contextual controls. Quieter labels and fewer
repeated slogans are design judgment, not an Apple compliance claim. Windows
window controls and system typography remain appropriate to the target platform.

## Verification

- Full Linux regression suite: **561 passed in 108.56 s** using
  `python -m pytest tests -q --timeout=60`, with independent reader binaries on PATH.
- After the final card-height adjustment: reran `tests/test_ux_shell.py` and
  `tests/test_app.py`; **17 passed**, including light/dark, narrow/wide and 200%
  text checks. These verify clipping, overlap and access to all tools/options.
- Added one behavior regression covering grouped-menu access, idle controls,
  unique status messages, error recovery and active progress/cancellation.
- Ruff lint, formatting and whitespace checks passed. Source `--self-test` passed.
- Luna supplied a bounded visual review. Terra reviewed cancellation, retries,
  output publication and packaging configuration; its targeted jobs, race,
  named-output and rename tests passed (**59 tests**). No confirmed high-risk
  defect was identified within that scope.

Screenshots below are synthetic Linux Qt captures at 1380 × 860, not Windows
runtime evidence:

- [Light library](polish/library-light.png)
- [Dark library](polish/library-dark.png)
- [Light workspace](polish/workspace-light.png)
- [Dark workspace](polish/workspace-dark.png)

## Remaining verification

This is a focused polish and regression review, not a complete independent
security/privacy audit or first-time-user study. No new speed or memory benchmark
was run, so no performance improvement is claimed. Native Windows rendering,
screen-reader behavior and the frozen executable still need verification for
this commit. Packaging configuration was inspected; Windows Actions and a new
release were not run. Changes are committed locally for review.
