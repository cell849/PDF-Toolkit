# Metadata coverage audit

This inventories the app's current inputs and common file families, not every
file format ever created. The test suite compares all registered conversion
input formats against registered privacy policies. A newly accepted input
format will fail that coverage check until its privacy behavior is accounted for.
Supported formats can still contain unsupported features; those fail explicitly.

| Family / extensions | Current privacy behavior |
| --- | --- |
| JPEG/JPG, PNG, WebP, TIFF/TIF, BMP, GIF | Same-format pixel rebuilding removes supported source metadata. Animated/multipage files rejected; normal PNG/TIFF precision retained where supported. |
| PDF | Basic Info/XMP removal, or stronger page-image rebuild without original hidden objects. Stronger mode loses selectable/vector structure. |
| Word DOCX | Editable package cleaner: properties, comments, revision identifiers, ordinary text revision acceptance, ZIP fields, supported embedded images. Headers/footers and normal formatting retained. |
| Excel XLSX | Editable package cleaner: properties, comments/author records, printer/cache metadata, ZIP fields, supported images. Visible cells, formulas and normal formatting retained. Hidden/protected content is rejected. |
| PowerPoint PPTX | Existing conservative editable cleaner: properties, notes/comments, ZIP fields, raster images. Complex presentations rejected. |
| OpenDocument ODT, ODS, ODP | Properties, settings/view data, comments/change history, thumbnails, ZIP fields and supported raster images cleaned. Current document content and normal styles retained. |
| RTF | Basic text/formatting-preserving cleaner removes known property/reviewer/history groups. Images, objects, fields, hidden text, revisions and unknown hidden destinations are rejected. |
| TXT, CSV | No standardized embedded author/GPS container fields. Optional neutral-name UTF-8 copy only; all textual contents/formulas/comments remain. |
| Markdown MD | Neutral-name copy only. YAML/TOML frontmatter is textual metadata and is **not** automatically removed. |
| Legacy Office DOC, XLS, PPT; binary XLSB | Unsupported. Save a modern DOCX/XLSX/PPTX copy using Word/Excel/PowerPoint/LibreOffice, then use the matching cleaner. Renaming the extension does not convert it. |
| Macro-enabled DOCM/XLSM/PPTM, DOTM/XLTM/POTM | Unsupported. Save a macro-free modern copy first. No active code is executed or retained by a supported cleaner. |
| Office templates DOTX/XLTX/POTX; OpenDocument OTT/OTS/OTP | Unsupported as templates. Save as a normal supported document before cleaning. |
| Flat OpenDocument FODT/FODS/FODP | Unsupported; save as packaged ODT/ODS/ODP. |
| Pages, Numbers, Keynote | Unsupported; export a supported Office/OpenDocument format and review fidelity. |
| Visio VSD/VSDX, Publisher PUB, Access MDB/ACCDB, OneNote ONE/ONEPKG | Unsupported; each needs a dedicated parser and hidden-content policy. |
| Outlook MSG/EML/PST/OST | Unsupported. Sender/recipient headers and attachment contents require an email-specific policy. |
| Google GDOC/GSHEET/GSLIDES shortcuts | These are links, not full local documents. Export a supported document first. |
| HEIC/HEIF, AVIF | Verified same-container pixel rebuilding; HEIC requires optional codec. Re-encoding may lose precision/color. |
| JPEG XL, JPEG 2000 | Unsupported by the verified cleaner/codec matrix. |
| Camera RAW CR2/CR3/NEF/ARW/DNG, Photoshop PSD, GIMP XCF | Unsupported. Raw/layer/history data need specialized handling; export a flattened supported image. |
| SVG, EPS, AI | Unsupported; vectors can contain scripts, links, text and editing metadata. |
| MP4/MOV/MKV/WebM/AVI, MP3/M4A/FLAC/WAV/OGG/AAC | Local FFmpeg primary-stream reconstruction to MP4 or FLAC; source tags, cover art, chapters and other streams dropped. |
| ZIP/7Z/RAR/TAR | Unsupported as a privacy-cleaned archive. Archive filenames/timestamps and every nested file need separate handling. |
| HTML, EPUB, XML, JSON, YAML | No dedicated cleaner. Metadata can be mixed with meaningful document content; do not treat an unchanged text copy as scrubbed. |
| Executables, installers, arbitrary binaries | Unsupported. Modifying them can invalidate signatures or break software. |

## Important payload exclusions

Word/Excel cleaning rejects charts, SmartArt, OLE/embedded documents, external
relationships/formulas, content controls/data bindings, macros, signatures,
embedded fonts and unsupported images. Word table-structure revisions must be
accepted in Word before cleanup. Hidden Word text and hidden/protected Excel
sheets/rows/columns/names are rejected. Normal Word text revisions are accepted
in the copy; old deleted text and reviewer records are removed.

OpenDocument objects, scripts/forms, external links, protected content and
unsupported package extensions are rejected. Comments/change history and
view/settings parts are deleted from the copy. Basic RTF cleanup intentionally
supports less than the full RTF specification.

All cleaners preserve original files and create separate output/report pairs.
Named styles, bookmarks, named ranges, document text/cells, headers/footers,
object labels, image pixels (including cropped/hidden image areas), and the
operating system's file metadata may still identify people. Removing supported
metadata is not a universal anonymity guarantee. Read the in-app policy and
review the actual output before sharing sensitive material.

Offline OCR now uses a separately installed Tesseract and its local language packs
(English `eng` by default). Scanned pages become searchable PDFs. Recognition can
be inaccurate; existing text pages are copied by default, including mixed pages.
OCR pages lose vector/interactive features; document bookmarks/forms/signatures
are not preserved. The tool bounds resolution, subprocess time and page size.


HEIC/HEIF and AVIF single images are now accepted by image tools when their local
codec is available. HEIC requires the optional media extra. Audio/video cleanup
accepts content-verified MP4/MOV/MKV/WebM/AVI/MP3/M4A/WAV/FLAC/OGG/AAC through
separately installed FFmpeg/ffprobe, with MP4 or FLAC reconstruction. Metadata
inspection supports these containers too. See docs/METADATA.md for destructive
format, stream and quality limits.

## Editable resizing and compression controls

PDF rendering and rasterized compression accept a custom DPI within supported
bounds, including 276 DPI. The raster pixel limit still applies. Changing the
print-DPI metadata of an existing image alone is not pixel resizing.

Image/PDF size targets accept an editable amount and KB/MB (decimal), KiB/MiB
(binary), or a percentage to **keep** of the original input bytes. A target is an
upper bound. Preserving resolution is the default: permitted quality adjustments
are tried, then an unattainable target fails without publishing output. Reducing
pixel dimensions/DPI for size targeting requires explicit permission. Images also
support percentage reduction of their dimensions, with aspect ratio retained.
