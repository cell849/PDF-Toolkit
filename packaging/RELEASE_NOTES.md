# Local PDF Toolkit 0.7.1

Fixes the tool library appearing as empty horizontal strips in 0.7.0.
A shared button style overrode card heights and collapsed their labels.
Cards now size to their content, including wrapped descriptions and enlarged
text, and rows reserve enough space to prevent overlap. Format badges also grow
with text size.

Regression checks cover every card in light/dark themes, compact/wide windows,
and changes between 100% and 200% text size. The packaged EXE self-test now checks
actual library labels and card geometry before testing a real conversion.
No new runtime dependencies were added.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the entire
folder and launch **LocalPDFToolkit.exe**. Keep `_internal` beside it. Source-code
archives are for development. A SHA-256 checksum accompanies the app ZIP.

This build remains unsigned; Windows SmartScreen may show an unknown-publisher
warning. All processing remains local. Optional conversion engines are installed
separately, as documented in CAPABILITIES.md.
