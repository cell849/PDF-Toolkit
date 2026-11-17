# Local PDF Toolkit 0.8.3

- Inline, resizable Options and Save copy sections push neighboring controls down;
  the sidebar and tool library now have more consistent spacing and navigation.
- Select All tools again to switch between the tool list and category overview.
- Enter custom DPI for OCR, flattened PDF cleaning and redaction; existing pixel
  limits still apply. Size-target reduction uses a clearer checkbox layout.
- Inspect common metadata values locally, grouped and searchable, including PDF
  and image XMP, Office properties, and supported audio/video tags with local
  ffprobe. Exported inspection reports remain masked. Coverage is not exhaustive;
  visible content and other metadata may remain. Media inspection can create
  temporary local files, which are cleaned up when the operation completes.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the complete
folder and open **LocalPDFToolkit.exe**. Keep `_internal` beside it. The source
archives are for development; a SHA-256 checksum accompanies the app ZIP.

The EXE is self-signed. This checks integrity but does not establish a trusted
publisher, so Windows SmartScreen warnings can remain. The hosted build uses a
temporary certificate; its public certificate and verification instructions are
included, but its private key is not distributed. Optional conversion engines
are installed separately. The app runs offline.
