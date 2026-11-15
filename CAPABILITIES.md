# Supported local tools

The registry is authoritative. All processing is local; no AI, API key, account,
telemetry or cloud conversion is included. This is not complete parity with every
button in the reference screenshots.

| Tool | Supported behavior and limits |
| --- | --- |
| PDF → JPEG / PNG | Selected pages; 72/150/300 DPI; JPEG quality; PNG alpha. Rasterizes text. |
| Images → PDF | Ordered JPEG/PNG/WebP/TIFF/BMP/GIF inputs; image-sized, A4 or Letter pages. Single-frame inputs only. |
| Image → JPEG / PNG / WebP / TIFF / BMP | Actual-content validation, EXIF orientation, aspect-preserving maximum dimensions; metadata removed. |
| Target-size images | Maximum KiB, quality and pixel dimensions; reduces quality/resolution as needed. Fails if unattainable. |
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

File size uses KiB (1024 bytes). PNG targeting can require resolution reduction;
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

Deferred tools: OCR (possible locally without cloud AI), secure redaction with a
region editor, arbitrary PDF content editing, interactive form authoring/filling,
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
