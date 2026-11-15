# Independent integrity checks

All fixtures are generated locally from synthetic values. The PDF writer and Office
ZIP/XML writers use the Python standard library, independently of production PDF
and Office document libraries. No external documents or copyrighted fixture corpus
are included. Image fixtures are tiny synthetic Pillow images.

`pdftotext`, `pdftoppm`, `pdfinfo`, and `pdfdetach` from Poppler verify PDF outputs.
qpdf expands PDF object streams before checks for hidden structures and canaries;
ExifTool independently reads converted-image metadata. Tests requiring a missing
external executable skip with an explicit reason. Tests otherwise use project
development dependencies only.

```bash
python -m pytest tests/quality_integrity -q
```

The compression limit regression supplies valid, extremely narrow synthetic pages,
but intercepts rasterization before any large pixel allocation. Publication tests
inject filesystem faults, run real concurrent publishers, and preserve foreign files.
Source preservation checks hash actual original bytes before and after conversion.

Cross-engine visual checks compare solid-color interiors. Small edge interpolation
differences between vector rendering and a rebuilt raster image are expected; they
are excluded from exact pixel comparisons. Text retention and page order are checked
separately through Poppler extraction. These bounded tests do not constitute broad
font/layout fidelity validation or Windows filesystem certification.
