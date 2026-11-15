# Local PDF Toolkit 0.7.0

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the entire
folder and launch LocalPDFToolkit.exe. Keep _internal beside it. The automatically
listed source-code archives are for development. A SHA-256 checksum is included.

## A document workspace

- A file list, embedded Original/Result preview, and collapsible options panel.
- Persistent success, partial-failure and cancellation feedback beside the main
  action; errors explain how to recover without scrolling to a hidden file row.
- Actual-content inspection before processing, compatible file carryover between
  tools and session-only restoration when returning to a previous tool.
- Clear menus, precise number fields without tiny steppers, consistent dropdowns,
  deliberate Ctrl+wheel adjustments and keyboard-safe DPI slider snapping.
- Original app icon in the window, taskbar and EXE, plus product/version metadata.
- On-demand comparison, zoom/page controls, transparency background and notices
  when a displayed result belongs to previous settings.
- Output names, collision recovery, undo of remove/reorder, file clipboard paste,
  whole-window drop feedback and a concise output/settings summary.
- Advanced options disclosure, engine-availability screen, text-size choices and
  remembered window/unit preferences. No persistent file history or document cache.

All conversion remains offline. Originals are preserved. OCR requires local
Tesseract/language packs, Office conversion requires LibreOffice, and audio/video
cleaning requires FFmpeg/ffprobe. The app downloads no engines at runtime.

## Windows signing

This build is **unsigned** because no trusted signing identity is configured.
Windows SmartScreen may show “Windows protected your PC” or “Unknown publisher”.
The icon, product metadata and checksum do not remove that warning. A checksum
checks integrity, not publisher identity. Even a newly signed app can require
reputation before SmartScreen stops warning. No Windows protection is disabled.

Automated Windows tests, GUI/resource smoke and frozen-worker conversion checks
gate publication. Interactive Windows 11/clean-machine verification remains a
separate step. This personal-use package retains its dependency/license notice.
