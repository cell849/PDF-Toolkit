Download **LocalPDFToolkit-Windows-x64.zip** under Assets.
Extract once and open **LocalPDFToolkit/LocalPDFToolkit.exe**, keeping `_internal` beside it.
No Python installation or terminal commands are needed.

This maintenance release preserves all 28 local tools and fixes reviewed input,
resource-management and UI issues. Searching now selects a visible tool and
cannot accidentally run a hidden selection. Tests and the packaged worker
self-test run on Windows before this release is created.

LibreOffice is separately required for Office-to-PDF. Reverse Office conversion
and lossy compression have limits explained in the app and CAPABILITIES.md.
The portable app is unsigned. Normal Windows 11 desktop validation remains a
manual check. This is a private personal-use build; see packaging/THIRD_PARTY.md.
