Closes the missing Office metadata-cleaning gaps while keeping the desktop style:

- DOCX: properties, reviewer/comments, normal text revision history, ZIP fields and supported images.
- XLSX: properties, comments, printer/cache metadata, ZIP fields and supported images; formulas/normal formatting retained.
- ODT/ODS/ODP: properties, settings, comments/change history, thumbnails and supported images.
- Basic RTF: known property/reviewer/generator/history groups, with unsupported payloads rejected.
- TXT/CSV/MD: separately labelled neutral-name UTF-8 copy; all textual content remains.
- A coverage regression accounts for every currently accepted input format.
- docs/FORMAT_COVERAGE.md lists support and common gaps; docs/TOOL_IDEAS.md ranks useful additions.

36 tools total. Metadata cleaning is not an anonymity guarantee. Visible content,
style/bookmark/sheet labels, named ranges, headers/footers and filesystem data can
remain. Complex/linked/active packages, unsupported hidden/protected content and
unsupported revisions are rejected. Originals are preserved. Read the in-app policy.

Download **LocalPDFToolkit-Windows-x64.zip**, extract once, and open
**LocalPDFToolkit/LocalPDFToolkit.exe** with `_internal` beside it.
Private unsigned personal-use build. LibreOffice is separate for Office-to-PDF;
the new editable package cleaners do not require LibreOffice at runtime.
