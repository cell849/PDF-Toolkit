# Local PDF Toolkit 0.8.1

- Simpler category-first home with search and explicit access to all tools.
- Visual PDF page organizer: thumbnails, multi-selection, drag/keyboard reorder,
  rotation, removal, insertion and undo. Saving verifies the reviewed source bytes.
- PDF comparison: highlighted visual differences and a bounded text-change report
  for two PDFs, matched by page number. No semantic or automatic page alignment claims.
- Improved comparison viewer with Fit, zoom, 100% preview pixels and linked panning.
- Batch status filters/counts and selected-file outcomes; retries preserve mapping.
- Image format comparison produces same-dimension JPEG, PNG and WebP candidates.
- PDF paper normalization offers DIN A/B/C 0–10, US and custom sizes, selected pages,
  orientation, margins and contain/cover behavior.
- Interrupted-job cleanup explicitly removes tracked abandoned staging while
  preserving originals and published outputs; active jobs are protected by locks.
- Contextual settings, clearer file-size results and inspection progress/caching.
- Lean developer checks and quieter logs; replaced repetitive size conversions with
  independent representative checks. Full Windows release gates remain enabled.
- Self-signed EXE with a public certificate and verification instructions included.
  No new runtime dependencies; processing remains offline.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the entire
folder and launch **LocalPDFToolkit.exe**. Keep `_internal` beside it. Source-code
archives are for development. A SHA-256 checksum accompanies the app ZIP.

Self-signing checks executable integrity but does not establish a trusted publisher.
Windows SmartScreen warnings can remain. No private signing key is distributed;
this hosted build uses a temporary certificate. See SIGNATURE.txt inside the ZIP.

Organizer/normalized pages can lose links/forms/document-level features; their
limits are shown in the app. Cropping is not redaction. Comparison uses bounded
rendering/extracted text and may miss small details; reports may contain personal
content. Crash cleanup only recognizes tracked safe staging, not legacy unknown
folders. Optional engines remain separate installations. Human accessibility and
clean-machine testing remain necessary alongside automated Windows checks.
