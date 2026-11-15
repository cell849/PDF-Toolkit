# Registered tool risk inventory

Inventory covers all 40 registered tools; it is not a claim that all format/content combinations were tested. Existing adapter tests remain; new integrity tests concentrate on shared publication, raster limits, privacy and independent output readers. UI forms/registry checks alone do not certify conversion fidelity.

| Operation | Tool | Review priority / reason |
| --- | --- | --- |
| `pdf.to_jpeg` | PDF to JPEG | High: output integrity / page or content fidelity |
| `pdf.to_png` | PDF to PNG | High: output integrity / page or content fidelity |
| `image.to_pdf` | Images to PDF (ordered files) | High: pixel bounds / size target / fidelity |
| `image.to_jpeg` | Image to JPEG / resize / compress | High: pixel bounds / size target / fidelity |
| `image.to_png` | Image to PNG / resize / compress | High: pixel bounds / size target / fidelity |
| `image.to_webp` | Image to WEBP / resize / compress | High: pixel bounds / size target / fidelity |
| `image.to_tiff` | Image to TIFF / resize / compress | High: pixel bounds / size target / fidelity |
| `image.to_bmp` | Image to BMP / resize / compress | High: pixel bounds / size target / fidelity |
| `pdf.merge` | Merge PDFs | High: output integrity / page or content fidelity |
| `pdf.split` | Split PDF into pages | High: output integrity / page or content fidelity |
| `pdf.extract` | Extract PDF pages | High: output integrity / page or content fidelity |
| `pdf.reorder` | Reorder PDF pages | High: output integrity / page or content fidelity |
| `pdf.delete` | Delete PDF pages | High: output integrity / page or content fidelity |
| `pdf.rotate` | Rotate PDF pages | High: output integrity / page or content fidelity |
| `pdf.crop` | Crop PDF margins | High: output integrity / page or content fidelity |
| `pdf.number` | Number PDF pages | High: output integrity / page or content fidelity |
| `pdf.watermark` | Add text watermark | High: output integrity / page or content fidelity |
| `pdf.remove_metadata` | Remove PDF properties (basic) | High: output integrity / page or content fidelity |
| `pdf.flatten` | Flatten PDF annotations and forms | High: output integrity / page or content fidelity |
| `pdf.protect` | Protect PDF with password | High: password / encryption correctness |
| `pdf.unlock` | Unlock PDF with password | High: password / encryption correctness |
| `pdf.to_text` | PDF to text | High: output integrity / page or content fidelity |
| `pdf.to_markdown` | PDF to Markdown | High: output integrity / page or content fidelity |
| `pdf.compress` | Compress PDF | High: pixel bounds / size target / fidelity |
| `office.to_pdf` | Office / text to PDF (LibreOffice) | High: native engines / cancellation / fidelity |
| `pdf.to_docx` | PDF to DOCX | High: output integrity / page or content fidelity |
| `pdf.to_xlsx` | PDF to XLSX | High: output integrity / page or content fidelity |
| `pdf.to_pptx` | PDF to PPTX | High: output integrity / page or content fidelity |
| `metadata.clean_image` | Clean image metadata | Critical: privacy / source integrity |
| `metadata.clean_pptx` | Clean PowerPoint metadata | Critical: privacy / source integrity |
| `metadata.clean_pdf` | Clean PDF metadata (flattened) | Critical: privacy / source integrity |
| `metadata.clean_docx` | Clean Word metadata (DOCX) | Critical: privacy / source integrity |
| `metadata.clean_xlsx` | Clean Excel metadata (XLSX) | Critical: privacy / source integrity |
| `metadata.clean_odf` | Clean OpenDocument metadata | Critical: privacy / source integrity |
| `metadata.clean_rtf` | Clean RTF metadata (basic) | Critical: privacy / source integrity |
| `metadata.neutral_text` | Neutral-name text / CSV copy | Critical: privacy / source integrity |
| `metadata.inspect` | Inspect / compare metadata | Critical: privacy / source integrity |
| `pdf.ocr` | Searchable PDF (Tesseract OCR) | High: native engines / cancellation / fidelity |
| `pdf.redact` | Redact marked PDF areas | Critical: privacy / source integrity |
| `metadata.clean_media` | Clean audio / video metadata (FFmpeg) | Critical: privacy / source integrity |
