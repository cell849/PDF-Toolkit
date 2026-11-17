# Local PDF Toolkit 0.8.2

- Replaced the scrolling right inspector with content-sized Options, Advanced and
  Save copy dropdowns. Oversized sections can scroll inside their popup, preventing
  fields from overlapping or being cut off.
- Moved requirements and detailed explanations to accessible info buttons, available
  on hover and by keyboard/click. Conversion errors remain prominent.
- Added a collapsible icon-only sidebar with tooltips and keyboard navigation.
- Refined slider tracks and thumbs, rounded choice menus, theme colors and display
  captions. Fixed slider gestures not updating the summary and stale-result state.
- Improved form spacing, paper-size readability and large-text layouts. Removed
  repeated slogans and long inline explanations. No runtime dependencies added.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the entire
folder and launch **LocalPDFToolkit.exe**. Keep `_internal` beside it. Source-code
archives are for development. A SHA-256 checksum accompanies the app ZIP.

The EXE is self-signed. This checks integrity but does not establish a trusted
publisher, so Windows SmartScreen warnings can remain. The hosted build uses a
one-time certificate; the ZIP includes its public certificate and verification
instructions, never its private key. Optional conversion engines remain separate.
The app runs offline. Human Windows accessibility and clean-machine testing remain
useful alongside automated checks.
