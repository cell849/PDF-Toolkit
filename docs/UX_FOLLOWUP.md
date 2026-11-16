# Contextual controls, inspection and signed builds

- Lossless PDF compression hides raster-only controls. Resolution reduction is
  shown when a size target and compatible mode make it relevant. Editable targets
  and all existing options remain available; changed values remain in summaries.
- Inspection progress shows completed/total files. Existing signature-based
  session caching and incremental list updates remain; modified inputs are
  inspected again. Conversion validation is retained. No extra parallel workers
  or unsafe parser bypasses were introduced.
- Successful selected results show measured output size, original size and percent
  smaller/larger. Sidecars are excluded; report-only tools show report size.
  Rasterized PDF results state lost text/links/forms based on saved run settings.
  Rename copies state metadata is retained. Missing outputs are handled clearly.
  Failures with no saved results explicitly say no output was saved.
- Self-signing is opt-in; see packaging/README.md. Public certificate and verifier
  ship with signed builds; private keys never ship. Self-signing does not establish
  a trusted publisher or remove SmartScreen warnings. CI certificates are ephemeral.

Apple design skill references actually consulted: layout.md, Visual hierarchy;
disclosure-controls.md, Best practices (hide details until relevant); and
progress-indicators.md (transient feedback for ongoing work). Native Windows
menus, focus and keyboard behavior are retained. No UI dependencies added.

Verification: 576 Linux tests passed; final affected UI rerun 32 passed after
layout and summary refinements; workflow/render harness 55 passed. Windows build
will run full tests, native UI at 150% scale, frozen EXE self-test, signature/digest
verification and a deliberate tamper rejection. No performance improvement beyond
existing v0.8 row-update measurements is claimed.
