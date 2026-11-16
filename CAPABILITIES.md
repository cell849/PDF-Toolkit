# Supported local tools

The registry is authoritative. All processing is local; no AI, API key, account,
telemetry or cloud conversion is included. This is not complete parity with every
button in the reference screenshots.

| Tool | Supported behavior and limits |
| --- | --- |
| PDF → JPEG / PNG | Selected pages; editable 10–1200 DPI; JPEG quality; PNG alpha. Rasterizes text. |
| Images → PDF | Ordered JPEG/PNG/WebP/TIFF/BMP/GIF/AVIF/HEIC inputs (available codecs); image-sized, A4 or Letter pages. Single-frame inputs only. |
| Image → JPEG / PNG / WebP / TIFF / BMP | Actual-content validation, EXIF orientation, aspect-preserving maximum dimensions; metadata removed. |
| Target-size images | Editable KB/MB/KiB/MiB or percent-to-keep target; preserves resolution by default. Optional downscaling. Fails if unattainable. |
| Merge PDF | Selected file-list order; preserves PDF text/vectors. |
| Split / extract / delete / reorder | Validated page ranges. Reorder requires every page exactly once, in stated order. |
| Rotate / crop | Selected pages; crop margins in PDF points. Crop is not redaction. |
| Number pages / watermark | Visible Latin text overlays; no secure redaction. |
| Metadata cleanup / flatten | Remove Info/XMP metadata; flatten annotation/form appearances. |
| Password protect / unlock | AES256 protection; unlock requires the correct password. No bypass or recovery. |
| PDF → text / Markdown | Extract existing text. Markdown adds page headings, without semantic layout reconstruction. |
| PDF → DOCX | Selectable text into paragraphs; original images/layout/tables not preserved. |
| PDF → XLSX | Detected tables only; no spreadsheet if no table is detected. Text is never executed as formulas. |
| PDF → PPTX | One image per slide; slide content is not editable. |
| DOCX/XLSX/PPTX/ODT/ODS/ODP/RTF/TXT/CSV → PDF | Requires installed LibreOffice. Fonts, layout and pagination can differ. UTF-8/UTF-16 text. CSV cells imported as literal strings. |
| Lossless PDF compression | Structural cleanup/deflation; keeps text and vectors; may not reduce size. |
| Target-size PDF compression | Explicit rasterized mode; size upper bound, not exact byte count. Discards selectable text, interactive content and links. |

File size units are explicit: KB/MB use 1000, KiB/MiB use 1024. PNG targeting can require resolution reduction;
JPEG/WebP can also reduce quality. Maximum dimensions preserve aspect ratio and
never enlarge an image. PDF size targeting uses bounded quality/resolution trials;
very large pages reduce render DPI to stay within the pixel guardrail. If a target
cannot be reached, no oversized result is published.

Input bounds: 512 MiB, PDF 10,000 pages, image/render 40 million pixels (additional
format-specific bounds apply). The converter process is separate from the UI,
not a security sandbox. Native calls can delay cooperative cancellation.

Office inputs with macros, embedded documents or external links are rejected.
An isolated LibreOffice profile disables macros and linked-content updates.
Legacy binary DOC/XLS/PPT, arbitrary HTML, and Pages files are not supported.
Some benign linked Office documents will consequently be rejected.

Deferred tools: arbitrary PDF content editing, interactive form authoring/filling,
digital certificate signatures, signing requests, PDF/A conformance validation,
repair guarantees, document comparison, scanner/camera hardware and ZIP imports.
These need dedicated interfaces, dependencies or correctness work; the app does
not show them as working tools. Additional reverse conversions are considered
individually because PDF usually lacks the source document's structure.

## Privacy tools — v0.4.0

Three additional tools (31 total) clean images, supported editable PowerPoint
presentations and flattened PDFs. The supported formats, destructive effects,
verification boundaries and exclusions are in docs/METADATA.md. This is metadata
cleaning rather than a universal anonymizer. The app lists limitations before
running and includes a report viewer; raw private metadata is never copied into
reports. Originals remain unchanged.

## v0.5.0 Office privacy expansion

36 tools total. Added DOCX/XLSX, OpenDocument and basic RTF cleaners plus a neutral-name
text copy tool. Every currently accepted input format has an explicit privacy policy.
See docs/FORMAT_COVERAGE.md for payload restrictions and common unsupported formats.


## v0.6.0 additions

40 registered tools. Metadata inspector compares parsed category counts without
exporting private values. Selected PDFs/images and supported Office documents
have a paged worker preview; Office rendering requires LibreOffice. AVIF support
depends on Pillow's codec; HEIC uses the optional `media` dependency extra.

Offline searchable-PDF OCR requires local Tesseract and language packs. Manual PDF
redaction uses visual area selection, content-bound marks and a fresh raster PDF;
all selectable text/interactivity is lost (see docs/REDACTION.md). Audio/video
cleanup requires local FFmpeg/ffprobe: primary video/audio becomes MP4 H.264/AAC,
audio-only becomes FLAC; other tracks, cover art, chapters and source tags are
dropped. These re-encode media and may change quality/color/timing. Visible and
audible personal information remains. See docs/METADATA.md.

Windows release publication is gated by its Actions test/package run. Saved presets were
excluded at the user's request. There are no cloud or AI tools.

Custom PDF render/compress DPI accepts 10–1200 within the 40 MP guard. Image and PDF
size targets accept editable KB/MB/KiB/MiB amounts or percent to keep of original
bytes; preserving resolution is default. Image percentage resizing and explicit
size-driven downscaling are available. Before/after previews render on demand.

## v0.7.0 workspace

The same 40 registered tools now share a document workspace: content-verified file
inspection, embedded Original/Result preview, visible result feedback, compatible
input carryover and session-only per-tool context. Settings changes mark old
results as previous runs. File removal/reorder can be undone; paste and whole-window
drag are supported. Output names are optional and never overwrite existing files.
Window geometry, split sizes, unit preference and text size may persist; document
paths/content and tool recipes do not. Availability checks locate optional local
engines without downloading them. Views support system appearance and larger text.

The EXE has an original icon and version information. Authenticode signing can be
requested by the local build script using an already-provisioned trusted certificate
thumbprint. No identity was supplied for this release, so SmartScreen warnings
remain possible. The checksum is not a signature or a reputation guarantee.

## 0.7.2 file utilities

**Batch rename copies** (Organize) supports the same verified input formats as the
metadata inspector. Edit a replacement basename (blank keeps source stems), prefix,
suffix, starting number and zero-padding width. A live table shows exact names in
input order. Saving creates byte-identical copies with original suffixes; metadata
remains. Originals are never renamed. Bounds: 1–10,000 files, existing parser/file
limits, safe Windows filenames and a conservative 259 UTF-16-unit destination path.
Encrypted/unsupported inputs are rejected. A collision or cancellation rolls back
the batch's published outputs without touching pre-existing files.

**Document details** (Organize) saves a JSON report viewable in the app. PDFs show
font resource names/embedding flags, encryption, rotated page dimensions in points
and attachment names/sizes without extraction. Locked PDFs show encryption/page
count and explicitly omit protected details. Dimensions/font scanning cover at most
200 pages, 256 distinct fonts and 100 attachment names; reports are capped at 64 KiB
with explicit truncation notices. Images show display-oriented pixel dimensions,
mode and stored DPI when available. Office packages show structural counts (such
as sheets/slides/paragraphs), not rendered page layouts or inferred font inventories.
Other accepted formats provide verified type/size. Names may contain personal text;
use the separate masked metadata inspector for a privacy inventory.

## Image comparison, paper normalization and recovery

**Compare image formats** generates JPEG, PNG and WebP copies at identical,
EXIF-oriented pixel dimensions with editable JPEG/WebP quality. All three outputs
are saved atomically; use Compare and its output selector for previews and exact
sizes. JPEG composites transparency onto white. Metadata is removed; multi-frame
images are rejected. This is a visual comparison, not an automatic quality score.

**Normalize page sizes** supports selected page ranges, DIN A0–A10, B0–B10 and
C0–C10, Letter/Legal/Tabloid and custom dimensions in mm/cm/in/pt. Orientation can
follow each page or use portrait/landscape. Contain fits the full visible page;
cover fills and crops visible edges. Margins are in mm. Text/vectors are retained
on selected pages; annotation/form appearances become permanent, with links and
interactivity removed. Unselected pages are copied. Bookmarks, attachments,
signatures and advanced document features are not preserved. Cropping is not
redaction. Page-size, page-count and render guardrails still apply.

**Tools → Clean up interrupted jobs** inspects registered staging jobs and offers
explicit cleanup. Startup checks only journal names and offers a review hint.
Per-job OS locks prevent cleanup of active jobs across app instances. Original
and published files are never removed by recovery; interrupted batches may retain
partial published outputs. Unknown folders, links, changed ownership and nested
staging contents are refused. Pre-existing untracked crash leftovers are not
swept. A writable per-user recovery state directory is required. Journals contain
staging/output paths and bounded output names, never file contents/passwords;
normal completion removes them, while interrupted records persist until cleanup.
