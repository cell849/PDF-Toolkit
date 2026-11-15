# Useful next tools — proposals, not implemented

| Priority | Tool | User value | Complexity / acceptance focus |
| --- | --- | --- | --- |
| 1 | Metadata inspector with before/after field counts | Shows what was detected and what a cleaner removed, instead of only its general policy. | Moderate. Mask personal values by default; compare actual parsed fields; never log raw values. |
| 2 | Document/image previews and page thumbnails | Makes page order, crop, rotation, compression and accidental selection errors easier to see. | Moderate. Render off the UI thread; bounded thumbnail cache; show actual resulting pages. |
| 3 | Saved batch presets / recipes | Repeats common convert/resize/compress/clean operations with fewer clicks. | Moderate. Respect destructive/lossy boundaries; run cleanup after conversions that add metadata; preserve source files. |
| 4 | Offline OCR / searchable PDFs | Makes scanned PDFs searchable and selectable. | Larger. Local Tesseract/language packs, cancellation and measured recognition quality; no cloud/API dependency. |
| 5 | Secure redaction with visual selection | Removes personal visible text/images that metadata cleanup cannot remove. | High. Remove underlying objects, scrub hidden/revision data and verify that redacted text cannot be extracted; drawing a rectangle is insufficient. |
| 6 | Broader photo and audio/video cleanup | Covers phone HEIC/AVIF and MP4/MOV/MP3 metadata gaps. | Larger. Verified codecs and format-aware ExifTool/FFmpeg integration, privacy checks and packaging/license review. |
| 7 | Duplicate finder and bulk rename | Organizes many similar files and avoids sending the wrong copy. | Moderate. File hashes, previewed rename plan, no deletion by default and reversible names. |
| 8 | Visual/text document comparison | Helps verify conversions and find changes between document versions. | Larger. Separate visual changes from extracted-text changes; align pages and explain limits. |

The first three are the best fit for the existing desktop app. OCR and secure
redaction add more capability but require dedicated correctness work. None of
these proposals has been implemented as part of this metadata expansion.
