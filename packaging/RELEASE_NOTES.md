Adds a **Privacy** category in the same desktop style:

- Clean metadata from JPEG/PNG/WebP/TIFF/BMP/single-frame GIF.
- Clean supported editable PPTX properties, notes/comments, ZIP fields, and embedded raster images.
- Rebuild PDF pages into a fresh flattened PDF without original hidden objects/attachments.
- Neutral unique output filenames and in-app cleaning reports. Originals are preserved.

Image cleaning re-encodes JPEG and removes ICC profiles; color appearance can
change. PPTX notes/comments are deleted in the copy; complex/linked/active
packages are rejected. The stronger PDF cleaner removes selectable text and
vector/editable structure. See docs/METADATA.md for exact scope and exclusions.
Visible personal content and filesystem metadata can remain. No file is labeled
anonymous, and unsupported formats are not silently passed through.

Download **LocalPDFToolkit-Windows-x64.zip**, extract once, and open
**LocalPDFToolkit/LocalPDFToolkit.exe**. Keep `_internal` beside it.
This remains a private unsigned personal-use build.
