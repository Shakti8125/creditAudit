# DISPATCH — worker_m2

## 2026-08-28T13:51:00Z
Received assignment for ModelAudit AI Milestone 2: Privacy Pipeline & Zero-Trust Masking Core.

### Assigned Issues:
1. PRV-01 (Critical): In `masking_pipeline.py`, replace global `.replace()` with character offset slice replacement executed in reverse order on `raw_text` using `resolved_spans`.
2. PRV-02 (Critical): In `egress_validator.py`, iterate over all `registry.get_mapping().keys()` and check if any original entity text is present in `masked_text`.
3. PRV-03 (High): In `egress_validator.py`, exclude valid bracket tokens (e.g. regex `^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]$`) from flagging as leaks.
4. PRV-04 (Medium): In `egress_validator.py`, support dependency injection of `NERMasker` and `BankNameMatcher` instances with module-level singleton fallbacks instead of recreating them on every call.
5. PRV-05 (High): In `bank_matcher.py`, fix Aho-Corasick `(end_char_index, matched_name)` off-by-one span calculation by converting to standard half-open `[start, end)`: `end_index = end_char_index + 1; start_index = end_index - len(matched_name)`.
6. PRV-06 (High): In `bank_matcher.py`, ensure lowercase case-insensitive matching and enforce word boundary checks (`not preceding.isalnum()`, `not following.isalnum()`) to avoid substring false positives on short bank abbreviations (e.g. "FAB", "CBD", "DIB", "Gulf").
7. PRV-07 (Low): In `gcc_bank_names.json`, fix typo `"Barclids"` to `"Barclays"`.
8. PRV-08 (High): In `ner_masker.py`, remove runtime `spacy.cli.download` call; raise clean `RuntimeError` prompting model installation if `spacy.load` fails.
9. PRV-09 (Medium): In `ner_masker.py`, expand `FINANCIAL_PATTERNS` regex to include all GCC currencies (`AED`, `SAR`, `QAR`, `KWD`, `BHD`, `OMR`, `USD`, `EUR`, `GBP`), formatted numbers with commas (`1,250,000`), percentages, ISO dates, and fiscal quarters.
10. PRV-10 (Medium): In `ner_masker.py`, configure `AnalyzerEngine` to share the existing spaCy NLP instance and set `score_threshold=0.6`.
11. PRV-11 (Medium): In `entity_registry.py`, implement atomic single-pass regex replacement in `unmask_text` to prevent sequential replacement corruption.
12. PRV-12 (Low): In `entity_registry.py`, strip leading/trailing whitespace in `mask()` and return `""` for empty strings.
13. Re-export public privacy classes in `services/privacy/__init__.py`.

### Exclusive File Ownership:
- `backend/app/services/privacy/masking_pipeline.py`
- `backend/app/services/privacy/egress_validator.py`
- `backend/app/services/privacy/bank_matcher.py`
- `backend/app/services/privacy/ner_masker.py`
- `backend/app/services/privacy/entity_registry.py`
- `backend/app/services/privacy/resources/gcc_bank_names.json`
- `backend/app/services/privacy/__init__.py`
