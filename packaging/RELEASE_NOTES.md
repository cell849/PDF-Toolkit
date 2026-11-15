# Local PDF Toolkit 0.6.0

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the complete
folder, and launch LocalPDFToolkit.exe. The automatically listed source archives
are for development. Keep the _internal folder beside the EXE.

- Editable DPI, including exact values such as 276, with slider landmarks.
- Editable size targets in KB, MB, KiB, MiB or percent of original file size.
- Image percentage resizing and explicit permission for size-driven downscaling;
  resolution is preserved by default and impossible targets fail clearly.
- On-demand before/after preview with dimensions and file sizes.
- Metadata inspection, document previews, offline OCR, visual PDF redaction,
  HEIC/AVIF photos and local audio/video cleanup.
- Safer extreme-page raster limits, resilient output cleanup and lower memory
  consumption for opaque images; independent integrity/regression tests added.

All conversion stays local. Originals remain untouched. OCR requires separately
installed Tesseract/language packs; Office conversion requires LibreOffice;
audio/video cleaning requires FFmpeg/ffprobe. No engine is downloaded at runtime.
PDF redaction reconstructs every page as pixels and loses selectable text and
interactivity. Metadata cleaning is not a guarantee of anonymity.

Automated Windows test/package results are attached to the release's source
commit in Actions. Manual Windows 11 desktop/clean-machine verification remains
separate. This personal-use package retains the dependency/license notice.
