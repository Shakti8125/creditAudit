# Deep Review Analysis: Document Extraction & Chunking

**Explorer**: explorer_3  
**Scope**: IBM Docling Extraction, Markdown Chunking, Table Preservation, Overlap Mechanics, Document API & Multi-Tenancy  
**Date**: 2026-08-29  

---

## 1. Executive Summary

This investigation conducted an exhaustive static analysis of the document extraction, chunking, and upload lifecycle in ModelAudit AI. The primary components audited include:
- `backend/app/services/document_extractor.py` (IBM Docling 2.0+ integration, PDF/Word options, error handling)
- `backend/app/services/chunker.py` (Header-aware chunking, financial comma preservation, atomic table handling, sliding window overlap)
- `backend/app/api/documents.py` (Upload pipeline, streaming spooling, privacy masking, Pinecone upsert, error recovery)
- `backend/app/models/document.py` & `backend/app/schemas/document.py` (ORM models and Pydantic v2 schemas)
- `backend/app/services/retrieval/hybrid_retriever.py` & `backend/tests/test_stress_chunking.py` (Integration validation)

### Key Verdict
The core extraction and chunking algorithms exhibit high technical rigor:
- Sentence splitting uses regex lookbehind `(?<=[.!?])\s+`, which completely prevents splitting on financial commas (e.g. `1,250,000`) and decimal numbers.
- Tables are atomically preserved and exempted from the 8-word minimum noise filter.
- Docling 2.0+ is properly configured with `WordFormatOption()` and `PdfFormatOption()`.
- Synchronous CPU-bound Docling and Regex operations are properly offloaded via threadpools (`loop.run_in_executor` and `run_in_threadpool`).

However, **two critical cross-module bugs and several edge cases** were discovered:
1. **Critical Namespace Mismatch**: `api/documents.py` upserts chunks to Pinecone namespace `str(tenant_id)`, whereas `hybrid_retriever.py` queries namespace `f"user-docs:{tenant_id}:{document_id}"`. This causes vector search for uploaded documents to silently return zero results.
2. **Logic Bug in Section Header Extraction**: `api/documents.py` (line 174) contains the condition `c.split(":\n")[0].count(" > ") >= 0`, where `>= 0` is a tautology (always True), causing arbitrary text with `:\n` to be misidentified as section headers.
3. **Hardcoded Chunk Count in API Listing**: `api/documents.py` (line 269) hardcodes `chunk_count=0` in `list_documents`.

---

## 2. Component-by-Component Deep Dive

### 2.1 IBM Docling Extractor (`backend/app/services/document_extractor.py`)

#### Code Review & Architecture
```python
# Lines 25-43
class DocumentExtractor:
    def __init__(self) -> None:
        pdf_opts = PdfPipelineOptions()
        pdf_opts.do_table_structure = True
        pdf_opts.table_structure_options = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        )

        self.converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
                InputFormat.DOCX: WordFormatOption(),
            },
        )
```

#### Evaluation Checklist
- **Python 3.12 Compatibility**: Fully compliant. Uses `from __future__ import annotations`, standard typing, and clean async integration.
- **Docling 2.0+ API**:
  - Correctly imports `DocumentStream` and `InputFormat` from `docling.datamodel.base_models`.
  - Correctly configures `TableFormerMode.ACCURATE` on `PdfPipelineOptions`.
  - Correctly uses `WordFormatOption()` mapped to `InputFormat.DOCX`.
  - Correctly uses `DocumentConverter(allowed_formats=..., format_options=...)`.
- **Async Execution**:
  - Docling's `convert()` is a CPU/native blocking operation. Line 76-77 offloads execution to the default thread pool executor via `loop.run_in_executor(None, _convert)`.
- **Error Handling**:
  - `DocumentExtractionError` is explicitly defined (lines 20-22) and raised with exception chaining `from exc` (line 74).
  - Validates file extensions (`pdf`, `docx`) before conversion (lines 59-63).

#### Identified Improvements & Minor Notes
- Line 76: In Python 3.12, `asyncio.to_thread(_convert)` can be used as a cleaner, modern shorthand for `loop.run_in_executor(None, _convert)`.
- Input typing: Supports both `bytes` and `typing.BinaryIO` (`SpooledTemporaryFile`), wrapping `bytes` into `BytesIO` and passing streams directly to `DocumentStream(name=filename, stream=stream_obj)`.

---

### 2.2 Markdown Chunker (`backend/app/services/chunker.py`)

#### Code Review & Architecture
```python
# Lines 20-23
def _is_table_line(self, line: str) -> bool:
    s = line.strip()
    return bool(s) and ((s.startswith("|") and s.endswith("|")) or s.count("|") >= 2)
```

```python
# Lines 55-70
if delimiter == "\n\n":
    raw_parts = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
    separator = "\n\n"
elif delimiter == "\n":
    raw_parts = [p.strip() for p in clean_text.split("\n") if p.strip()]
    separator = "\n"
elif delimiter == ". ":
    raw_parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", clean_text) if p.strip()]
    separator = " "
elif delimiter == " ":
    raw_parts = [p.strip() for p in clean_text.split(" ") if p.strip()]
    separator = " "
```

#### Evaluation Checklist
- **Financial Comma Preservation**:
  - Splitting on sentence boundaries uses `re.split(r"(?<=[.!?])\s+", clean_text)`.
  - In financial text such as `AED 1,250,000.50`, commas `,` are never matched by `[.!?]`.
  - The decimal point `.` in `1,250,000.50` is followed by digits `50`, not whitespace `\s+`.
  - Therefore, financial amounts, ratios, percentages (e.g. `2.45%`), and privacy tokens (`[BANK_1]`, `[ORG_1]`) remain completely unbroken.
- **Table Preservation & Exemption**:
  - Tables are identified line-by-line via `_is_table_line()` and grouped into atomic blocks `( "table", block_lines )`.
  - Text blocks are subjected to `len(rc_clean.split()) >= 8` to filter out OCR/PDF noise.
  - Table blocks bypass the 8-word filter completely (`chunks.append(header_context + table_content)` at line 205), preserving compact validation summary tables (e.g., AUC, Gini, KS benchmark tables).
- **Hierarchical Header Context**:
  - Detects markdown headers `#` through `######` (lines 221-230).
  - Maintains `current_headers` dictionary and prepends `"{H1} > {H2}:\n"` to every chunk.
  - Reset mechanism properly clears sub-headers when a higher-level header is encountered (`current_headers[i] = "" for i in range(level + 1, 7)`).
- **Sliding Window Overlap**:
  - `_accumulate_with_overlap()` collects units up to `chunk_size`.
  - On overflow, it extracts the trailing units matching `overlap` (lines 115-121) and carries them forward to the next chunk.
  - Includes a safety pop loop (lines 123-129) ensuring the overlap units plus the new unit never exceed `chunk_size`.
  - Final deduplication check prevents identical consecutive chunks (line 144).

#### Edge Cases & Nuances
1. **False Positive Table Lines**:
   `s.count("|") >= 2` treats any text line containing two or more pipe characters as a table line (e.g., `Option 1 | Option 2 | Option 3`). For Docling markdown, tables have leading/trailing pipes (`| ... |`), so this is rarely problematic, but could misclassify pipe-separated inline text.
2. **Oversized Tables**:
   An atomic table with 100+ rows (~10,000 chars) will be emitted as a single chunk exceeding `chunk_size`. If an embedding model has a hard token limit (e.g., 512 or 2048 tokens), embedding this chunk could truncate or error. However, for standard CBUAE validation reports, tables are under 30 rows.
3. **Short Standalone Non-Table Sentences**:
   Text blocks with fewer than 8 words (e.g. `"Rating: AAA."` or `"Default Definition: 90 DPD."`) are filtered out if they appear as their own standalone section/block.

---

### 2.3 Document Upload API Pipeline (`backend/app/api/documents.py`)

#### Code Review & Architecture
```python
# Lines 83-97: Spooled Temporary File for memory safety
spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
try:
    total_bytes = 0
    while True:
        chunk = await file.read(CHUNK_READ_SIZE)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="File too large (max 50MB)")
        await run_in_threadpool(spool.write, chunk)
```

#### Bugs & Findings in `api/documents.py`

#### Finding 1 (Critical): Pinecone Namespace Inconsistency
- **Location**: `backend/app/api/documents.py`, line 169 vs `backend/app/services/retrieval/hybrid_retriever.py`, line 203 & `backend/tests/test_stress_multitenancy.py`, line 139.
- **Observed Code**:
  ```python
  # backend/app/api/documents.py (line 169-170)
  pinecone_store = PineconeStore()
  namespace = str(current_user.tenant_id)
  ```
  ```python
  # backend/app/services/retrieval/hybrid_retriever.py (line 201-203)
  namespaces = ["cbuae-manuals"]
  if document_id:
      namespaces.append(f"user-docs:{tenant_id}:{document_id}")
  ```
- **Impact**: When a user queries a document via `/query`, `hybrid_retriever` looks in Pinecone namespace `user-docs:{tenant_id}:{document_id}`. Since `upload_document` uploaded the vectors to `{tenant_id}`, dense retrieval returns 0 results for the uploaded document!
- **Resolution**: Update `api/documents.py` line 169 to:
  ```python
  namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"
  ```

#### Finding 2 (High): Tautological Regex/Count in Section Extraction
- **Location**: `backend/app/api/documents.py`, lines 173-176.
- **Observed Code**:
  ```python
  for c in chunks:
      section = ""
      if ":\n" in c and c.split(":\n")[0].count(" > ") >= 0:
          section = c.split(":\n")[0]
      chunk_data_list.append(ChunkData(source=safe_filename, section=section, text=c))
  ```
- **Impact**: `c.split(":\n")[0].count(" > ") >= 0` is a tautology (always True). If a chunk body contains `":\n"` anywhere (e.g. `"The model results are as follows:\n1. AUC = 0.85"`), `section` is set to `"The model results are as follows"`, corrupting the section metadata.
- **Resolution**: Check that `":\n"` occurs at the start and does not contain line breaks, or verify that `c` matches the header pattern:
  ```python
  for c in chunks:
      section = ""
      if ":\n" in c:
          potential_sec = c.split(":\n", 1)[0]
          if "\n" not in potential_sec:
              section = potential_sec
      chunk_data_list.append(ChunkData(source=safe_filename, section=section, text=c))
  ```

#### Finding 3 (Medium): Hardcoded `chunk_count=0` in `list_documents`
- **Location**: `backend/app/api/documents.py`, line 269.
- **Observed Code**:
  ```python
  metadata_list = [
      DocumentMetadata(
          id=d.id,
          filename=d.filename,
          file_type=d.file_type,
          upload_time=d.upload_time,
          status=d.status,
          chunk_count=0,
      )
      for d in docs
  ]
  ```
- **Impact**: In the document listing UI, `chunk_count` always displays as `0` instead of the actual number of generated chunks.
- **Resolution**: Use `selectinload(Document.chunks)` or a `func.count(DocumentChunk.id)` subquery to return accurate chunk counts.

---

## 3. Verification of Requirements

| Requirement | Implementation File | Status | Notes |
|---|---|---|---|
| **Python 3.12 Compatibility** | `document_extractor.py`, `chunker.py`, `documents.py` | **Verified** | Clean async, no deprecated APIs, proper typing. |
| **IBM Docling 2.0+ & Word Format Options** | `document_extractor.py:37-43` | **Verified** | `WordFormatOption()` and `PdfFormatOption()` properly passed to `DocumentConverter`. |
| **Financial Comma Preservation** | `chunker.py:62` | **Verified** | `re.split(r"(?<=[.!?])\s+", clean_text)` preserves `1,250,000.50`, currencies, and tokens. |
| **Unified Table Preservation** | `chunker.py:202-205` | **Verified** | Tables are kept atomic and exempted from the 8-word min filter. |
| **Sliding Window Overlap** | `chunker.py:86-147` | **Verified** | Reverse scan with boundary protection and deduplication. |
| **Structured Error Handling** | `document_extractor.py:20-22, 71-74`, `documents.py:223-246` | **Verified** | `DocumentExtractionError` raised, DB rolled back, `DocumentStatus.ERROR` set. |

---

## 4. Remediation Proposals & Diff Patches

### Proposed Fix 1: Align Pinecone Namespace & Section Parsing in `api/documents.py`
```python
# In backend/app/api/documents.py around lines 168-178:
<<<<
            pinecone_store = PineconeStore()
            namespace = str(current_user.tenant_id)

            chunk_data_list = []
            for c in chunks:
                section = ""
                if ":\n" in c and c.split(":\n")[0].count(" > ") >= 0:
                    section = c.split(":\n")[0]
                chunk_data_list.append(ChunkData(source=safe_filename, section=section, text=c))
====
            pinecone_store = PineconeStore()
            namespace = f"user-docs:{current_user.tenant_id}:{doc_id}"

            chunk_data_list = []
            for c in chunks:
                section = ""
                if ":\n" in c:
                    potential_header = c.split(":\n", 1)[0]
                    if "\n" not in potential_header:
                        section = potential_header
                chunk_data_list.append(ChunkData(source=safe_filename, section=section, text=c))
>>>>
```

### Proposed Fix 2: Add Explanatory Inline Comments in `document_extractor.py`
```python
# In backend/app/services/document_extractor.py:
# Add comments clarifying:
# - Why TableFormerMode.ACCURATE is critical for credit risk validation tables
# - Why WordFormatOption() is registered for InputFormat.DOCX
# - Why conversion is executed via loop.run_in_executor
```
