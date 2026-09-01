---
name: p2-document-extraction
description: >-
  Use this skill to build the document extraction and chunking system for ModelAudit AI. This includes IBM Docling integration, Markdown chunking, SQLAlchemy models, Pydantic schemas, and FastAPI routes for document upload and management.
---

# Document Extraction and Chunking System

Follow these steps exactly to build the document extraction and chunking pipeline for Phase 2.

## Step 1: IBM Docling Integration (`backend/app/services/document_extractor.py`)

Create `backend/app/services/document_extractor.py`.

Implement the `DocumentExtractor` class:
- `__init__` should configure `DocumentConverter` for BOTH PDF and DOCX.
- Imports required:
  ```python
  from io import BytesIO
  from docling.document_converter import DocumentConverter, PdfFormatOption
  from docling.datamodel.base_models import InputFormat, DocumentStream
  from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions, TableFormerMode
  ```
- Initialize PDF pipeline options: `do_table_structure=True`, `TableStructureOptions(mode=TableFormerMode.ACCURATE, do_cell_matching=True)`.
- Format options dictionary should be: `{InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts), InputFormat.DOCX: ...}`
- Implement async method: `async def extract_to_markdown(self, file_bytes: bytes, filename: str) -> str`
  - Auto-detect format from filename extension (`.pdf` or `.docx`). Raise `ValueError` for unsupported types.
  - Wrap bytes in `DocumentStream(name=filename, stream=BytesIO(file_bytes))`
  - Process with converter and return `result.document.export_to_markdown()`

## Step 2: Header-Aware Markdown Chunker (`backend/app/services/chunker.py`)

Create `backend/app/services/chunker.py`.

Implement the `MarkdownChunker` class:
- `__init__(self, chunk_size=2400, overlap=400)`
- Splitting logic:
  - First split on headers (`#`, `##`, `###`, `####`), then `\n\n`, then `\n`, then `. `, then ` `
  - **CRITICAL**: NEVER split on commas (must preserve financial numbers like `1,250,000`).
  - **CRITICAL**: Preserve bracketed tokens like `[ORG_1]`, `[BANK_1]` — never split mid-token.
- Implement method: `def chunk(self, text: str) -> list[str]`
  - Returns a list of chunk strings.
  - Each chunk must include its parent header context as a prefix.
  - Drop any fragments shorter than 8 words.

## Step 3: SQLAlchemy Models (`backend/app/models/document.py`)

Create `backend/app/models/document.py`.

Define the following models:
- `Document`:
  - `id`: UUID (Primary Key)
  - `tenant_id`: UUID (Foreign Key)
  - `user_id`: UUID (Foreign Key)
  - `filename`: String
  - `file_type`: String
  - `upload_time`: DateTime
  - `raw_markdown`: Text
  - `status`: Enum (PROCESSING, READY, ERROR)
  - `metadata_json`: JSONB / JSON
- `DocumentChunk`:
  - `id`: UUID (Primary Key)
  - `document_id`: UUID (Foreign Key)
  - `chunk_index`: Integer
  - `masked_text`: Text
  - `embedding_id`: String (nullable)

## Step 4: Pydantic Schemas (`backend/app/schemas/document.py`)

Create `backend/app/schemas/document.py`.

Define the following Pydantic schemas:
- `UploadResponse`: `document_id`, `filename`, `file_type`, `page_count`, `chunk_count`, `masking_report`, `metrics_summary`
- `DocumentMetadata`: `id`, `filename`, `file_type`, `upload_time`, `status`, `chunk_count`
- `DocumentListResponse`: `documents: list[DocumentMetadata]`

## Step 5: FastAPI Router (`backend/app/api/documents.py`)

Create `backend/app/api/documents.py`.

Implement the FastAPI router:
- `POST /documents/upload`: Accept `UploadFile` (PDF/DOCX, max 50MB). Extract markdown, run analytics, mask entities, chunk text, embed, and store in DB. Returns `UploadResponse`.
- `GET /documents`: List all documents for the current tenant.
- `GET /documents/{id}`: Get document metadata and chunks (ensure tenant isolation).
- `DELETE /documents/{id}`: Delete document, its chunks, and associated Pinecone vectors.
- Ensure all endpoints enforce tenant isolation using a `get_current_user` dependency.

## Verification

After implementation:
1. Upload a sample PDF and DOCX.
2. Verify markdown extraction preserves table structure.
3. Verify chunking produces correct-sized chunks that include header context and do not split financial numbers or entity tokens mid-way.
