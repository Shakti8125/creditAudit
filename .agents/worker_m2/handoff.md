# Handoff Report — Worker M2 (Privacy Pipeline & Zero-Trust Masking Core)

## 1. Observation
The audit report (`backend_code_audit_report.md`) identified 12 specific bugs across the privacy pipeline subsystem plus missing module exports:
- `masking_pipeline.py:70-78` (PRV-01): `masked_text = masked_text.replace(entity_text, token)` replaced strings globally, replacing common words (e.g. "may", "credit") and corrupting nested bracket tokens.
- `egress_validator.py:33-57` (PRV-02): `validate` accepted `registry` but never checked `registry.get_mapping().keys()` against `masked_text`, allowing unmasked entities to slip through when NER missed them on second pass.
- `egress_validator.py:43-46` (PRV-03): Bracket tokens (e.g., `[ORG_1]`, `[BANK_1]`) detected as entities by spaCy caused false-positive egress violation errors, blocking valid masked documents.
- `egress_validator.py:30-32` (PRV-04): Instantiated fresh `NERMasker()` and `BankNameMatcher()` on each instance, reloading ~800MB spaCy model into memory repeatedly.
- `bank_matcher.py:38-40` (PRV-05): Off-by-one span calculation `start_index = end_index - len(matched_name) + 1` caused slice operations on half-open intervals `[start, end)` to truncate the last character of matched bank names.
- `bank_matcher.py:29-31, 38` (PRV-06): Exact case-sensitive matching failed to match lowercase bank names, and lack of word boundary checks matched substrings inside ordinary words (`"FABRIC"`, `"CONFIDENT"`, `"Gulfstream"`).
- `gcc_bank_names.json:36` (PRV-07): Typo `"Barclids"` instead of `"Barclays"`.
- `ner_masker.py:46-48` (PRV-08): Runtime `spacy.cli.download` blocked container startup/execution instead of cleanly raising `RuntimeError`.
- `ner_masker.py:26-38` (PRV-09): `FINANCIAL_PATTERNS` omitted GCC currencies (`SAR`, `QAR`, `KWD`, `BHD`, `OMR`), comma-separated numbers (`1,250,000`), percentages, ISO dates, and fiscal quarters.
- `ner_masker.py:50, 77-81` (PRV-10): Presidio `AnalyzerEngine()` loaded a duplicate spaCy model in memory instead of sharing the existing instance with `score_threshold=0.6`.
- `entity_registry.py:43-57` (PRV-11): Sequential string replace in `unmask_text` caused prefix collisions and sequential substitution corruption.
- `entity_registry.py:25-41` (PRV-12): `mask()` did not strip whitespace, producing duplicate tokens for `"Emirates NBD"` and `"Emirates NBD "`.
- `services/privacy/__init__.py` (Issue 13): Empty `__init__.py` with 0 exports.

## 2. Logic Chain
1. **PRV-01**: In `masking_pipeline.py`, sorting `resolved_spans` in descending order of `start` offset and performing `masked_text = masked_text[:span["start"]] + token + masked_text[span["end"]:]` guarantees exact slice substitution at original character positions without index drift, preserving non-entity words like "may" and preventing token corruption.
2. **PRV-02 & PRV-03 & PRV-04**: In `egress_validator.py`, checking `if original_entity in masked_text:` for every `original_entity` in `registry.get_mapping().keys()` catches any residual entity text. Introducing `VALID_TOKEN_PATTERN = re.compile(r"^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]$")` filters out legitimate masking tokens so they are not flagged as leaks. Supporting `__init__(bank_matcher=None, ner_masker=None)` with module singleton getters `get_bank_matcher()` and `get_ner_masker()` eliminates redundant model loads.
3. **PRV-05 & PRV-06 & PRV-07**: In `bank_matcher.py`, setting `end_index = end_char_index + 1` and `start_index = end_index - len(canonical_name)` aligns with Python's half-open interval `[start, end)`. Adding words in lowercase to the automaton, running queries on `text.lower()`, and verifying `not text[start_index - 1].isalnum()` and `not text[end_index].isalnum()` prevents substring false positives on abbreviations like "FAB", "CBD", "DIB", and "Gulf". Typo `"Barclids"` was fixed to `"Barclays"` in `gcc_bank_names.json`.
4. **PRV-08 & PRV-09 & PRV-10**: In `ner_masker.py`, replacing `spacy.cli.download` with a clean `RuntimeError` ensures graceful failure when `en_core_web_lg` is missing. Expanding `FINANCIAL_PATTERNS` to cover all GCC currencies, comma numbers, percentages, basis points, ratios, ISO dates, named dates, and fiscal quarters protects financial metrics. Configuring Presidio's `SpacyNlpEngine` with `spacy_engine.nlp = {"en": self.nlp}` shares the spaCy model at `score_threshold=0.6`.
5. **PRV-11 & PRV-12**: In `entity_registry.py`, `unmask_text` constructs a single compiled regex `re.compile("|".join(re.escape(token) for token in sorted_tokens))` and performs atomic replacement via `pattern.sub(lambda m: self._reverse[m.group(0)], masked_text)`. In `mask()`, `entity = entity.strip()` normalizes whitespace and returns `""` for empty strings.
6. **Issue 13**: `backend/app/services/privacy/__init__.py` re-exports all public privacy classes and singleton helper functions in `__all__`.

## 3. Caveats
- `en_core_web_lg` must be downloaded during Docker/CI image provisioning (`python -m spacy download en_core_web_lg`). When missing, `ner_masker.py` cleanly raises `RuntimeError` prompting installation. For testing and DI environments, `NERMasker(nlp=...)` accepts any pre-loaded `spacy.Language` instance.
- No files outside the 7 explicitly owned privacy files were modified.

## 4. Conclusion
All 13 assigned issues (PRV-01 through PRV-12 and `__init__.py` exports) have been successfully resolved, verified, and unit/integration tested. The Zero-Trust Privacy Pipeline enforces complete entity anonymization, prevents token false-positives, maintains financial number protection, and provides atomic single-pass unmasking.

## 5. Verification Method
1. **Compilation Check**:
   ```bash
   python -m py_compile backend/app/services/privacy/entity_registry.py
   python -m py_compile backend/app/services/privacy/bank_matcher.py
   python -m py_compile backend/app/services/privacy/ner_masker.py
   python -m py_compile backend/app/services/privacy/masking_pipeline.py
   python -m py_compile backend/app/services/privacy/egress_validator.py
   python -m py_compile backend/app/services/privacy/__init__.py
   ```
2. **End-to-End Pipeline & Integrity Verification**:
   ```python
   import spacy
   from app.services.privacy import (
       BankNameMatcher,
       EgressValidator,
       EgressViolationError,
       EntityRegistry,
       MaskingPipeline,
       NERMasker,
   )

   nlp = spacy.blank("en")
   ner = NERMasker(nlp=nlp)
   bm = BankNameMatcher()
   pipe = MaskingPipeline(bank_matcher=bm, ner_masker=ner)

   text = "First Abu Dhabi Bank processed AED 1,250,000 and 42% for FY2024. The model may underestimate default probability."
   masked, reg = pipe.mask_document(text)
   assert "AED 1,250,000" in masked
   assert "42%" in masked
   assert "FY2024" in masked
   assert "may" in masked
   assert "First Abu Dhabi Bank" not in masked

   val = EgressValidator(bank_matcher=bm, ner_masker=ner)
   rep = val.validate(masked, reg)
   assert rep.is_clean is True

   restored = reg.unmask_text(masked)
   assert "First Abu Dhabi Bank" in restored
   ```
