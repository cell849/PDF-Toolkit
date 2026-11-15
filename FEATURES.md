# Local PDF Toolkit — Prioritized Feature Backlog

Status: Proposed. P0 features are the initial approved target; later features require explicit approval before implementation.

## Priority definitions

- **P0:** Required for the first useful offline application.
- **P1:** Useful and likely next, but not a blocker for initial release.
- **P2:** Advanced features with substantial complexity or fidelity limits.
- **Parking lot:** Ideas, not commitments.

## P0 — First release

| ID | Feature | Acceptance criteria |
| --- | --- | --- |
| F001 | PDF to JPEG | Render all/specified pages at user-selected DPI and quality, deterministic names, correct page count. |
| F002 | PDF to PNG | Render all/specified pages with supported color/transparency behavior; validate output dimensions. |
| F003 | JPEG/PNG to PDF | Convert single or multiple images into a PDF with explicit ordering and page sizing. |
| F004 | Merge PDFs | Combine PDFs in selected order without rasterizing pages; clearly report encrypted/invalid inputs. |
| F005 | Split/extract PDF pages | Accept validated ranges and write ordered, correctly named PDF outputs. |
| F006 | Drag-and-drop UI | Import files; show supported actions, options, destination, and result links. |
| F007 | Job queue and batch conversion | Show queued/running/done/failed statuses; avoid UI blocking; cancel or retry jobs. |
| F008 | Safety and local processing | Never change source files; avoid unauthorized overwrites; clean temporary files; do not upload or send telemetry. |
| F009 | Verification and benchmarks | Conversion fixture tests, a 100-page benchmark, memory/time measurement, and reproducible test commands. |

## P1 — After the first release

| ID | Feature | Reason / caveat |
| --- | --- | --- |
| F101 | DOCX to PDF | High usefulness; requires optional local LibreOffice and fidelity testing. |
| F102 | XLSX/PPTX to PDF | Useful but layout and print-area behavior may vary. |
| F103 | WebP/TIFF to/from common images | Extend the image adapter, checking Windows codec availability. |
| F104 | PDF rotation and rearrangement | Structural modification, often without rasterization. |
| F105 | Basic PDF compression | Clearly distinguish lossless structural cleanup from lossy image recompression. |
| F106 | Preview thumbnails | Cache locally and bound memory; avoid slowing bulk conversion. |

## P2 — Consider only after demand and feasibility review

| ID | Feature | Reason / caveat |
| --- | --- | --- |
| F201 | OCR/searchable PDFs | CPU-heavy, external OCR and language packs; measurable accuracy requirements. |
| F202 | PDF to editable DOCX | Reconstructed structure can be inaccurate; must warn about fidelity. |
| F203 | HEIC/AVIF and additional formats | Codec/redistribution and Windows environment differences. |
| F204 | Redaction and advanced editing | Security-sensitive: visual hiding is not secure deletion. |

## Parking lot

- e-signatures and form workflows
- metadata editing
- password protection and permissions
- text extraction and CSV exports
- PDF/A conversion
- macOS/Linux packaging
- CLI automation mode

## How new features are selected

For each proposal, record:

1. User problem and example input/output.
2. Frequency or demonstrated value (don't invent demand).
3. Conversion fidelity and failure modes.
4. Estimated implementation and ongoing maintenance cost.
5. License and external dependencies.
6. Performance impact and measurable acceptance criteria.

The agent may propose and rank unapproved features but may not implement them without user approval. Any requested modification to an existing P0 feature is evaluated against its acceptance criteria; do not use it as permission to expand scope.

## User-authorized scope expansion — 2026-11-11

The user authorized continued implementation without a prompt between milestones,
with **M2 → M3 → M5 → M4**, broad non-AI local tools, reverse conversions where
meaningful, and maximum file size / resolution controls. This supersedes the
original requirement to separately approve M5 and the newly listed tools below.

Implemented adapters and explicit limitations are maintained in CAPABILITIES.md.
The expanded target includes image format conversion, structural PDF tools,
password operations, text exports, limited DOCX/XLSX/PPTX reverse exports,
LibreOffice forward conversion and compression. Format pairs must remain honest;
reverse conversion does not imply faithful reconstruction of the original.

Acceptance gates: real parser validation; originals unchanged; bounded workers;
per-job cancellation/errors/retry; output collisions refused; meaningful fixture
coverage; target-size success means output bytes <= configured maximum. An
unattainable target fails without publishing an oversized result. Rasterized
compression must disclose loss of selectable text and interactive content.

OCR, redaction/editor/signing/scanning and remaining screenshot tools are deferred
as documented in CAPABILITIES.md; no AI features are included.

## Metadata cleaner expansion — user requested

Add format-aware privacy tools with the existing desktop styling: image metadata,
conservative editable PPTX cleaning (including embedded raster images), and a
flattened PDF cleaner. Preserve originals; use neutral unique output names and
safe output transactions. Unsupported payloads must fail rather than be declared
clean. No universal “no personal data” guarantee is made. See docs/METADATA.md.

Acceptance: synthetic EXIF/GPS/XMP/comment/author canaries removed; source bytes
unchanged; containers parse; transparency/orientation/high-bit-depth samples
verified; PPTX notes/comments/properties removed with slide content/geometry
retained; unknown/active/complex media rejected; PDF source hidden objects not
copied; reports contain no source personal values; cancellation and collisions
leave no partial output. New tools share the Privacy sidebar category and
integrated report viewer.

## v0.5.0 — Office metadata gaps and format audit

User requested missing Office cleaners and a broader file-type audit. Add DOCX,
XLSX, packaged OpenDocument ODT/ODS/ODP and conservative RTF cleanup, with neutral
TXT/CSV/MD copying explicitly distinguished from embedded-metadata removal.
Keep desktop styling and all previous functions. Test content/style/formula
preservation, ordinary Word revision acceptance, unsupported-feature failures,
private-value removal, package fields, output rollback and actual Office loading.

Registered input formats must all have an explicit privacy policy; track common
unsupported formats in docs/FORMAT_COVERAGE.md. New tool suggestions are proposals
only, ranked in docs/TOOL_IDEAS.md, not automatically added to implementation.
