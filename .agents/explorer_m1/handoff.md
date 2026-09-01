# Handoff Report — Explorer M1: Privacy Pipeline & Document Extraction

## 1. Observation
Direct observations of source code and configurations across target files:
- **`masking_pipeline.py:70-78`**: Uses `masked_text = masked_text.replace(entity_text, token)` in a loop over unique entity strings, discarding character offset boundaries.
- **`egress_validator.py:33-57`**: `registry` parameter is accepted in `validate(self, masked_text: str, registry: EntityRegistry)` but never read. Additionally, spaCy `ORG`/`PERSON` detections are flagged as violations without checking if the text matches valid bracket tokens like `[ORG_1]`.
- **`bank_matcher.py:38-40`**: `start_index = end_index - len(matched_name) + 1` and `matches.append((start_index, end_index, matched_name))` where `end_index` is inclusive last character index from `pyahocorasick.iter()`, conflicting with `range(span["start"], span["end"])` and Python standard half-open slices `[start, end)`.
- **`bank_matcher.py:29-31, 38`**: Casing is not normalized and word boundaries are not verified.
- **`ner_masker.py:46-48`**: Calls `spacy.cli.download("en_core_web_lg")` inside `__init__` at runtime.
- **`ner_masker.py:26-38`**: `FINANCIAL_PATTERNS` omits GCC currencies (`SAR`, `QAR`, `KWD`, `BHD`, `OMR`), comma-separated numbers without currency, quarter dates, and ISO dates.
- **`chunker.py:40-55`**: `current_part` is reset to `""` in every loop iteration; text is never accumulated to `chunk_size`.
- **`chunker.py:12-14`**: `self.overlap` is stored but never used in splitting or chunk creation.
- **`chunker.py:94`**: `len(rc_clean.split()) >= 8` silently drops lines under 8 words, destroying markdown table rows.
- **`document_extractor.py:40-47`**: `converter.convert` lacks exception handling for corrupted documents.
- **`backend/app/api/documents.py:60, 81, 85`**: Instantiates heavy NLP models inside upload request handler.

## 2. Logic Chain
1. **Privacy Masking Integrity**: Discarding span offsets and executing global `str.replace(entity_text, token)` replaces common English words across the entire document whenever a name or organization matches a normal dictionary word. It also replaces substrings within previously inserted tokens (e.g. `[BANK_1]` becomes `[[ORG_2]_1]`).
2. **Egress Zero-Trust Vulnerability**: When a document contains sensitive entities, context changes can cause spaCy to miss an entity on second pass. Because `egress_validator` ignores `registry`, unmasked entities escape undetected. Conversely, when spaCy tags `[BANK_1]` as an entity, the validator fails on validly masked text.
3. **Indexing Inconsistency**: `ahocorasick` yields inclusive end indices. Downstream slicing and overlap resolution treat end index as exclusive. This creates an off-by-one error where the last character of every bank match is omitted.
4. **Chunker Malfunction**: Because `current_part` is never accumulated across loop iterations, `_split_text` breaks text into single lines/phrases instead of ~2,400-character chunks, and completely ignores the 400-character overlap requirement.

## 3. Caveats
- No code was executed or modified (strictly read-only audit).
- spaCy and Presidio behavior on specific domain texts should be verified with automated unit tests once fixes are applied.
- Docling 2.0+ performance on large scanned multi-page PDF documents depends on hardware resources (OCR engines/TableFormer).

## 4. Conclusion
The Privacy Pipeline and Document Extractor modules contain **4 Critical, 6 High, 6 Medium, and 6 Low severity bugs** (total 22 findings). The most pressing issues are:
1. Fixing `masking_pipeline.py` to use reverse character offset slicing instead of global `str.replace`.
2. Fixing `egress_validator.py` to check `registry.get_mapping().keys()` and exempt bracket token patterns.
3. Fixing `bank_matcher.py` span indexing to standard half-open `[start, end)` and adding word boundary checks.
4. Fixing `chunker.py` accumulation loop, implementing `overlap`, and preserving Markdown tables.

Full details are documented in `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\explorer_m1\report.md`.

## 5. Verification Method
1. Inspect `report.md` at `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\explorer_m1\report.md`.
2. Review line-by-line findings against the source code at `backend/app/services/privacy/` and `backend/app/services/chunker.py`, `backend/app/services/document_extractor.py`.
3. Once implementers apply fixes, verify via automated unit tests covering entity collision, case variation, egress validation with bracket tokens, and chunk accumulation with overlap.
