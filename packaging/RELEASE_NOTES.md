# Local PDF Toolkit 0.7.2

- Slim, rounded scrollbars with quiet tracks, clean corners and hover/drag feedback
  in light and dark themes. Standard wheel, keyboard and dragging behavior remains.
- **Batch rename copies** under Organize: preview names as you edit a replacement
  name, prefix, suffix and numbering; reorder inputs before saving. Copies keep
  their original bytes and extensions. Originals stay untouched. Existing output
  names fail safely; a failed batch rolls back its own outputs.
- **Document details** under Organize: PDF fonts, page sizes, encryption and
  attachment names; image dimensions/DPI; Office structural counts. Saved reports
  open inside the app. Locked PDFs show encryption restrictions without unlocking.
  Attachment contents are never extracted. Report lists are bounded with notices.
- Removed obsolete fixture/duplicate discovery tests and implementation-specific
  Qt assertions. Retained data-safety, integrity, worker and visible-layout checks;
  added focused coverage for the two new tools. No new runtime dependencies.

Batch rename supports the app's verified document/image/media formats, within
existing file/parser limits. It preserves metadata. Details reports can contain
font and attachment names; the masked metadata inspector remains separate.
Presets and image cropping were not added.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the entire
folder and launch **LocalPDFToolkit.exe**. Keep `_internal` beside it. Source-code
archives are for development. A SHA-256 checksum accompanies the app ZIP.

This build remains unsigned; Windows SmartScreen may show an unknown-publisher
warning. All processing remains local. Optional engines are installed separately.
