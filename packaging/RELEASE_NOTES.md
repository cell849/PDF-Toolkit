# Local PDF Toolkit 0.8.0

- Privacy fixes: reject protected Word files that could retain protection hashes,
  hidden web-view Word text, hidden PowerPoint XML text/invalid relationships,
  and external-workbook OpenDocument formulas.
  Review or remove those structures in Office before cleaning. Visible content
  remains outside metadata-cleaning guarantees.
- Fix HEIC metadata inspection format recognition.
- Improve Office subprocess cleanup and classify malformed Office rename inputs
  as invalid files, preserving batch rollback and originals.
- Faster inspection feedback for large file lists: update the affected row instead
  of rebuilding the entire list on every inspection completion.
- Calmer library typography, grouped tool menus, contextual progress/preview
  controls and persistent error recovery. All 42 tools remain available.
- Expanded Windows release verification includes native Qt workflows at 150%
  scale and a frozen EXE self-test. No new runtime dependencies.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the entire
folder and launch **LocalPDFToolkit.exe**. Keep `_internal` beside it. Source-code
archives are for development. A SHA-256 checksum accompanies the app ZIP.

This build remains unsigned; Windows SmartScreen may show an unknown-publisher
warning. Optional engines are installed separately. All processing remains local.
Cooperative cancellation cleans up outputs; an OS/native-process crash can leave
an incomplete staging directory. Human Windows accessibility and clean-machine
checks remain necessary; automated runner checks are not a usability study.
