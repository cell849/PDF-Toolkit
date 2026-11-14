# Synthetic test fixtures

`one_page.pdf` is a minimal, synthetic one-page PDF containing the text
"Local PDF Toolkit fixture" on a 612 x 792 point page. It contains no personal
data, encryption, JavaScript, external references or embedded files.

M0 checks its basic integrity; M1 uses it in real conversion and worker/UI tests.
Other tests generate 100-page, mixed-size, rotated, scanned, transparent,
encrypted/corrupt and non-ASCII-named documents in temporary directories.
