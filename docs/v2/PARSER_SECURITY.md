# V2 Parser Resource-Safety Gates

Status: implemented and covered by `tests/test_parser_security.py`.

The upload byte cap alone does not bound decompressed Office XML/media or rendered PDF pages. Parser entry
therefore applies independent budgets before handing untrusted content to `python-docx`, `python-pptx`,
`pypdfium2`, Pillow or OCR.

## Enforced budgets

| Environment variable | Default | Enforcement point |
|---|---:|---|
| `MAX_UPLOAD_BYTES` | 10,000,000 | API request read |
| `MAX_ARCHIVE_ENTRIES` | 2,048 | Office ZIP central directory |
| `MAX_ARCHIVE_UNCOMPRESSED_BYTES` | 50,000,000 | sum of Office entry sizes |
| `MAX_ARCHIVE_ENTRY_BYTES` | 20,000,000 | each Office entry |
| `MAX_ARCHIVE_COMPRESSION_RATIO` | 200 | entries at least 1 MB after expansion |
| `MAX_PDF_PAGES` | 200 | parsed page tree before extraction/rendering |
| `MAX_IMAGE_PIXELS` | 25,000,000 | raster decode and estimated PDF page render |

Office preflight also rejects encrypted entries, traversal/absolute paths, NUL names and embedded
`vbaProject.bin`. All limits apply to both synchronous upload and the durable ingestion worker.

## Test strategy

The deterministic suite sends seeded malformed bytes to each binary parser family and asserts only stable
4xx `AppError` failures escape. Crafted ZIP metadata exercises entry count, aggregate expansion, per-entry
size, compression ratio, traversal and macro cases. Generated PDFs exercise page count and pre-render pixel
budgets. An HTTP test proves application settings are passed to the parser rather than tested only in an
isolated helper.

This is a reproducible regression corpus, not a claim of exhaustive parser safety. A higher-assurance
deployment should additionally run workers in restricted containers, keep parser dependencies patched and
feed a coverage-guided fuzz campaign into the same stable failure contract.
