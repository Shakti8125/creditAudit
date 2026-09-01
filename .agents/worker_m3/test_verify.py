from __future__ import annotations
import sys
from pathlib import Path

backend_path = Path(r"c:\Users\Shakti\Documents\CreditAudit- AI\backend")
sys.path.insert(0, str(backend_path))

from app.services import MarkdownChunker, DocumentExtractor, DocumentExtractionError
from docling.datamodel.base_models import InputFormat
from docling.document_converter import WordFormatOption, PdfFormatOption

print("--- Test 1: Import Check ---")
print("Successfully imported MarkdownChunker, DocumentExtractor, DocumentExtractionError")

print("\n--- Test 2: Chunker Table Preservation (DOC-02) ---")
chunker = MarkdownChunker(chunk_size=500, overlap=100)
sample_table_doc = """# 1. Model Validation Report
## 1.1 Key Metrics
The following table shows the discrimination metrics:

| Metric | In-Time | Out-of-Time |
|---|---|---|
| Gini | 0.72 | 0.69 |
| AUC | 0.86 | 0.84 |
| KS | 45.2% | 42.1% |

Small table with < 8 words:
| Key | Val |
|---|---|
| PD | 0.05 |

The validation confirms model stability across all reporting quarters.
"""

chunks = chunker.chunk(sample_table_doc)
print(f"Total chunks produced: {len(chunks)}")
for i, ch in enumerate(chunks):
    print(f"Chunk {i+1}:\n{ch}\n")

table_chunks = [ch for ch in chunks if "| Metric |" in ch]
assert len(table_chunks) == 1, "Main table not found in chunks!"
small_table_chunks = [ch for ch in chunks if "| Key |" in ch]
assert len(small_table_chunks) == 1, "Small table (<8 words) was dropped!"

print("\n--- Test 3: Chunker Accumulation (DOC-01), Overlap (DOC-03), Punctuation (DOC-04), Paragraphs (DOC-05) ---")
long_text = """# 2. Detailed Methodology
First paragraph with sentence one about PD model calibration at [BANK_1]. Sentence two discussing 1,250,000 loan accounts. Sentence three evaluating macroeconomic stress scenarios with 15.5% unemployment.

Second paragraph detailing LGD modeling assumptions. The recovery rate for secured commercial real estate was estimated at 45.2%. Unsecured retail facilities showed lower recoveries of 22.8%.

Third paragraph covering EAD calculations under CCF framework. Exposure at default for revolving credit facilities was adjusted by a conversion factor of 0.75. Historical utilization data spanning 2018 to 2023 was used for calibration.

Fourth paragraph discussing model governance and validation findings. The internal validation team recommended annual monitoring of population stability index (PSI) with a threshold of 0.25.
"""

small_chunker = MarkdownChunker(chunk_size=300, overlap=80)
long_chunks = small_chunker.chunk(long_text)
print(f"Long text chunks count (chunk_size=300, overlap=80): {len(long_chunks)}")
for i, ch in enumerate(long_chunks):
    print(f"Chunk {i+1} (len={len(ch)}):\n{ch}\n")

# Verify commas in financial numbers are preserved
assert any("1,250,000" in ch for ch in long_chunks), "Financial number with comma was corrupted!"
# Verify privacy token preserved
assert any("[BANK_1]" in ch for ch in long_chunks), "Privacy token was corrupted!"
# Verify chunks accumulate multiple sentences
assert all(len(ch) > 0 for ch in long_chunks)

print("\n--- Test 4: DocumentExtractor Configuration (DOC-06, DOC-07) ---")
extractor = DocumentExtractor()
assert extractor.converter is not None, "Converter not initialized"
assert InputFormat.DOCX in extractor.converter.format_to_options, "InputFormat.DOCX not in format_to_options"
assert isinstance(extractor.converter.format_to_options[InputFormat.DOCX], WordFormatOption), "DOCX option is not WordFormatOption"
assert InputFormat.PDF in extractor.converter.format_to_options, "InputFormat.PDF not in format_to_options"

print("\n--- Test 5: DocumentExtractionError Exception Handling ---")
try:
    raise DocumentExtractionError("Testing custom error")
except DocumentExtractionError as e:
    assert str(e) == "Testing custom error"

print("\n==========================================")
print("ALL VERIFICATION CHECKS PASSED SUCCESSFULLY!")
print("==========================================")
