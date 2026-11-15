# Tool status and further proposals

The user approved five tools in stages; they are now implemented locally:

| Tool | Behavior / limits |
| --- | --- |
| Metadata inspector | One file or original/cleaned comparison; parsed category counts, private values masked. |
| Document/image previews | Paged, bounded worker rendering; temporary cache, optional LibreOffice for Office files. |
| Offline OCR | Local Tesseract/language packs; scanned PDF to searchable PDF, with recognition/layout limits. |
| Manual secure redaction | Visual marks, content binding, black pixel masks and verified fresh raster PDF; selectable text/interactivity lost. |
| Broader media cleaning | Optional HEIC codec and AVIF photos; separately installed FFmpeg for primary-stream MP4/FLAC reconstruction. |

Saved batch presets/recipes (the previous proposal 3) were excluded by the user.
No publishing or push is authorized for these changes.

## Useful further tools — proposals only

| Priority | Tool | Use case and acceptance focus |
| --- | --- | --- |
| 1 | Exact duplicate finder | Identify identical files by hashes; show a review list, no automatic deletion. |
| 2 | Visual/text PDF comparison | Check versions and conversion results side by side; distinguish page pixels from extracted text changes. |
| 3 | Contact sheets | Export a printable thumbnail index of PDF pages or a folder of photos, with optional filenames/page numbers. |
| 4 | PDF bookmarks/table of contents | Add or edit navigation in long documents without rasterizing content. |
| 5 | AcroForm filler | Fill existing standard PDF form fields locally; preview and optionally flatten. Reject unsupported XFA forms. |
| 6 | Extract embedded images | Export original PDF image resources without re-rendering whole pages; distinguish masks and duplicate resources. |

These are suggestions, not additional approved implementation work.
