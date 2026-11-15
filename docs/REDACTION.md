# Manual PDF redaction

Choose “Redact marked PDF areas”, add exactly one PDF, then choose “Mark areas…”.
Drag over sensitive areas and review each page using the page control. Choose
“Use marked areas”, select the output folder and run. Marks are bound to the
selected file and rejected if the file changes. Originals stay untouched.

The output is a fresh PDF containing only rendered page images. Marked pixels
are replaced with opaque black, with a small outward safety margin. All source
PDF objects are discarded, including searchable text, attachments, hidden layers,
scripts, forms and interactive annotations. Unmarked visible content remains.
The default rendering resolution is 150 DPI (72 and 300 are available).

This deliberately loses selectable text, vectors, bookmarks and interactivity
on every page. It cannot find sensitive areas automatically. Inspect the final
copy before sharing: content outside marks, depicted people and pixel
steganography remain. The policy report contains counts, not original text or
mark coordinates. File system data is outside the document-cleaning policy.
