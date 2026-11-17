# Version 0.8.5

- The category overview places Browse all tools first and aligns its title with search.
- Tool cards have consistent sizing, with the scrollbar at the outside edge.
- Sidebar selection and workspace controls have clearer, consistent styling;
  Home, Options and search align at different text sizes.
- Tool cards are now parented before display to prevent temporary startup windows.
- The project code is available under the MIT license; bundled dependencies have
  their own license terms, as described in the included third-party notice.

Download **LocalPDFToolkit-Windows-x64.zip** under Assets, extract the complete
folder and open **LocalPDFToolkit.exe**. Keep `_internal` beside it. The source
archives are for development; a SHA-256 checksum accompanies the app ZIP.

The EXE is self-signed. This checks integrity but does not establish a trusted
publisher, so Windows SmartScreen warnings can remain. The hosted build uses a
temporary certificate; its public certificate and verification instructions are
included, but its private key is not distributed. Optional conversion engines
are installed separately. The app runs offline.
