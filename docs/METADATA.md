# Metadata cleaning and its limits

Open **Privacy** in the desktop sidebar. Choose a cleaner, add files, select an
output folder and run it. Every successful job produces a clean copy with a
neutral random filename and a `.report.json` sidecar. Select a completed file
and use **View cleaning report** to read the policy and limits inside the app.
Outputs are staged together and existing files are never overwritten. Originals
are preserved. Batch jobs receive separate neutral names.

There is no safe universal cleaner for every file format. This release supports
JPEG, PNG, WebP, TIFF, BMP, single-frame GIF, a conservative editable PPTX subset,
and PDFs rebuilt as page images. Unsupported formats and unsupported package
features fail visibly. They are not copied through with a “clean” status.

## Images

The cleaner decodes and rebuilds the image into a new file of the same format;
source bytes, thumbnails, comments and trailers are not copied. EXIF/GPS,
IPTC/XMP, ICC and descriptive TIFF tags are omitted. EXIF orientation is applied
before removal. Required structural data (dimensions, pixel layout, TIFF strip
locations, PNG transparency, JPEG decoding structure) remains.

PNG transparency and supported high-bit-depth PNG/TIFF samples are retained.
CMYK/other color modes may be normalized. JPEG is re-encoded at quality 95;
WebP is encoded losslessly. Removing ICC profiles can alter color appearance.
Animated GIF/WebP and multi-page TIFF are rejected to avoid silent frame loss.
Limits are 512 MiB and 40 million decoded pixels.

Pixel content is preserved, including visible names, faces, writing and
potential pixel steganography. Transparent-pixel content is not a guaranteed
redaction. This tool removes supported metadata; it cannot promise anonymity.

## Editable PowerPoint

The conservative cleaner removes document core/extended/custom properties,
notes and note masters, comments/author/person records, thumbnails, tags,
printer/view properties and extension/custom-data bags. Notes and comments are
deleted in the new copy. ZIP timestamps are fixed to 1980; comments/extras are
omitted. Media filenames, relationship IDs, shape/theme metadata labels and
namespace prefixes are neutralized. Supported embedded raster images are
cleaned with the image policy above.

Editable slide text, pictures, geometry and normal styling remain. Visible
personal information, hidden slides/shapes and information conveyed by fonts,
layout or slide content may remain. Removing extension bags and image color
profiles can affect advanced appearance. The cleaner verifies that the result
opens with the PowerPoint parser, but this is not a guarantee of identical
rendering in every PowerPoint version.

Presentations containing charts, SmartArt, embedded Office/OLE files, custom XML,
external links, embedded fonts, vector/video/audio media, macros or signatures
are rejected. Encrypted, malformed, duplicate/noncanonical ZIP paths and oversized
packages are rejected. No macros or linked resources are executed. The cleaner
is a format validator, not a document security sandbox.

## PDF — flattened copy

The stronger PDF cleaner creates a fresh PDF from rendered page images. It
copies no original PDF objects: metadata/XMP, attachments, scripts, hidden text,
interactive forms/annotations, links and incremental revision data are omitted.
Visible page content and annotation appearances remain. Page dimensions are
preserved; rasterization removes selectable text and vector/editable structure.
Choose 72/150/300 DPI; exceptionally large pages may require the lower value.
The existing basic PDF Info/XMP removal tool remains available when preserving
PDF structure matters; its narrower scope is shown in that tool's limitations.

## What a report means

Reports list cleaning policy categories, safe technical output facts, and
limitations. They do not copy original metadata values, source filenames or
paths, or precise original timestamps. Policy categories indicate what the
cleaner omits; they do not claim the source contained every category.

The new output's technical/container fields and filesystem metadata remain.
Operating systems can assign timestamps, owners, permissions, file indexes,
backup records and cloud-sync history. The original file still exists. Visible
personal content, hidden Office content and steganography require separate
review/redaction. A successful job is not an anonymity certificate or a claim
that no personal information exists anywhere in the file or computer.

## Word, Excel and other Office files — v0.5.0

The Privacy category now includes DOCX, XLSX, ODT/ODS/ODP and basic RTF tools.
They preserve editable content where supported while deleting documented
properties, reviewer/comment/history fields, ZIP metadata and supported embedded
raster-image metadata. DOCX ordinary text changes are accepted in the copy;
complex table revisions/content controls are rejected. Excel formulas, visible
cells and normal formatting remain; protected/hidden content is rejected.
Protected Word documents (including write protection) and text hidden in Word's
web view are rejected. OpenDocument external formula references are rejected,
including relative references to other spreadsheet files.
OpenDocument properties/settings/comments/history/thumbnails are removed. RTF
cleanup is limited to basic text/formatting files and rejects unsupported payloads.

TXT/CSV/MD have a separate neutral-name copy tool whose policy explicitly says
textual contents are unchanged. It does not claim to scrub Markdown frontmatter,
CSV comments or personal names in text. All tools still create neutral unique
outputs and in-app reports, leaving originals unchanged.

See [the complete coverage audit](FORMAT_COVERAGE.md) for legacy files, templates,
other Office applications and remaining media formats. A coverage regression
checks that every input format already accepted by this app is accounted for.

## Inspecting and previewing

“Inspect metadata / compare copies” accepts one supported document/image, or two
files ordered original then cleaned. It reports parsed field/category counts and
before/after differences. Private values, custom field names and source filenames
are excluded. Counts cover recognized fields, not a proof of anonymity; visible
content and unrecognized structures require separate review.

“Preview selected” renders a page in a separate worker. PDFs and supported images
work locally; Office previews require installed LibreOffice and may differ with
available fonts. Page previews are bounded to 1400 pixels and kept in a temporary
directory removed when the viewer closes. Original files are unchanged.

### AVIF and HEIC photos

AVIF is supported when the installed Pillow build includes its codec. HEIC/HEIF
uses optional `pillow-heif` (`pip install -e '.[media]'`). The Windows packaging
recipe installs that extra. These photos join image conversion, image-to-PDF,
inspection and preview, as well as same-container metadata cleaning. Cleanup
rebuilds a single image from decoded pixels at quality 95; alpha is retained.
High bit depth/color modes may normalize to 8-bit RGB/RGBA and removing profiles
can change color. Multi-image/animated files are rejected. HEIC depth/auxiliary
images and thumbnails are omitted. No codec is downloaded at runtime.

### Audio and video

“Clean audio / video metadata” requires separately installed local FFmpeg and
ffprobe. It verifies containers independently of filename, snapshots the source,
and re-encodes the primary video/audio streams to MP4 H.264/AAC, or audio-only to
FLAC. It drops source tags, chapters, subtitles, cover art, attachments and other
tracks; no original encoded stream is copied. Generated technical container and
codec fields remain. Reports contain category counts, never source tag values.

Input/output are bounded to 512 MiB, input duration to one hour, video to 40
million pixels and audio to eight channels/192 kHz. Each process has a timeout;
cancel terminates its process tree. Partial/truncated output is rejected.
Encoding can change quality, color and timing; video normalizes to 8-bit YUV420p
and pads odd dimensions, audio-only FLAC uses 24-bit samples. Voices, depicted
people, visible text and steganography remain. This is not an anonymity guarantee.
