# Explorer M1 Audit Report: Privacy Pipeline & Document Extraction Services

**Scope**:
- `backend/app/services/privacy/entity_registry.py`
- `backend/app/services/privacy/bank_matcher.py`
- `backend/app/services/privacy/ner_masker.py`
- `backend/app/services/privacy/masking_pipeline.py`
- `backend/app/services/privacy/egress_validator.py`
- `backend/app/services/privacy/__init__.py`
- `backend/app/services/chunker.py`
- `backend/app/services/document_extractor.py`
- Dependency interactions (`requirements.txt`, `backend/app/services/privacy/resources/gcc_bank_names.json`)

---

## 1. Executive Summary

A comprehensive read-only code audit was conducted on the Privacy Pipeline and Document Extraction services of ModelAudit AI. A total of **22 distinct findings** were identified across 8 target source files and associated resources:

| Severity | Count | Key Impact Areas |
|---|:---:|---|
| **Critical** | **4** | Unanchored global string replacement corrupting English words and tokens; unused registry in egress validator; broken chunker accumulation fragmenting text; table destruction in chunker |
| **High** | **6** | Off-by-one span indexing in BankMatcher; case-insensitivity & substring false positives; masked token false positive egress blocking; blocking runtime spaCy CLI download; zero overlap in chunker; per-request heavy model instantiation |
| **Medium** | **6** | Incomplete financial number regex patterns; duplicate spaCy model loading in Presidio; delimiter stripping in chunker; empty line stripping breaking paragraph splitting; sequential unmasking replacement; unhandled docling conversion exceptions |
| **Low** | **6** | Missing `WordFormatOption` DOCX configuration; missing type annotations on `__init__` and legacy `typing` aliases; empty `__init__.py`; typo in bank names JSON dataset; missing Google-style docstring sections |

---

## 2. Per-File Detailed Findings

### 2.1 `backend/app/services/privacy/masking_pipeline.py`

#### Finding M1-01 (Critical)
- **File**: `backend/app/services/privacy/masking_pipeline.py`
- **Line(s)**: 70–78
- **Severity**: Critical
- **Category**: Privacy pipeline logic
- **Description**:
  In lines 70–78, `mask_document` collects unique entity text strings and performs unanchored global substring replacements via `masked_text = masked_text.replace(entity_text, token)`. This discards the resolved character offset spans (`resolved_spans`) calculated in Steps 1–3.
  This causes three major flaws:
  1. **Over-masking normal English words**: If a common word is recognized as an entity in one location (e.g. person name "Will" or "May", or organization "Credit", "Bank", "General", "Total"), `replace()` replaces *every* occurrence of that word across the document (e.g. `"The model may underestimate default probability"` becomes `"The model [PERSON_1] underestimate default probability"`).
  2. **Corruption of already-placed masking tokens**: If an entity is `"BANK"`, `"ORG"`, or `"1"`, executing `replace("BANK", "[ORG_2]")` replaces characters inside existing tokens, corrupting `[BANK_1]` into `[[ORG_2]_1]`.
  3. **Circumvention of span overlap resolution**: Overlap resolution logic performed on character indices is invalidated because raw string substitution is executed globally.
- **Correct Pattern / Fix**:
  Perform replacement directly on character offsets in descending order of `start` index (so earlier string offsets remain valid):
  ```python
  # Sort resolved spans by start offset descending
  resolved_spans.sort(key=lambda s: s["start"], reverse=True)
  masked_text = raw_text
  for span in resolved_spans:
      token = registry.mask(span["text"], span["category"])
      masked_text = (
          masked_text[:span["start"]] + token + masked_text[span["end"]:]
      )
  ```

---

### 2.2 `backend/app/services/privacy/egress_validator.py`

#### Finding M1-02 (Critical)
- **File**: `backend/app/services/privacy/egress_validator.py`
- **Line(s)**: 33–57
- **Severity**: Critical
- **Category**: Security issues / Privacy pipeline logic
- **Description**:
  The `registry: EntityRegistry` parameter passed to `validate(self, masked_text: str, registry: EntityRegistry)` is completely ignored and unused inside the method.
  `EgressValidator` only re-runs `BankNameMatcher` and `NERMasker`. In privacy pipelines, statistical NER models (spaCy) frequently fail to re-detect residual entities once the surrounding context has changed (e.g. when adjacent tokens have been replaced with `[BANK_1]`).
  Without checking the registered entity strings in `registry.get_mapping().keys()`, any entity that spaCy fails to flag upon second pass will leak directly to LLM providers undetected.
- **Correct Pattern / Fix**:
  Check all registered entity strings directly against `masked_text` in addition to re-running the matchers:
  ```python
  def validate(self, masked_text: str, registry: EntityRegistry) -> EgressReport:
      violations: list[str] = []
      
      # 1. Deterministic check: ensure none of the registered original entities exist in masked_text
      mapping = registry.get_mapping()
      for original_entity in mapping.keys():
          if original_entity in masked_text:
              violations.append(f"Registered entity leak detected: '{original_entity}'")

      # 2. Check for bank name leaks
      bank_matches = self.bank_matcher.find_matches(masked_text)
      for _, _, text in bank_matches:
          violations.append(f"Bank name leak detected: {text}")

      # 3. Check for NER leaks (excluding valid token notations)
      ner_matches = self.ner_masker.find_entities(masked_text)
      token_pattern = re.compile(r"^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE)_\d+\]$")
      for ent in ner_matches:
          if ent.category in ("ORG", "PERSON", "EMAIL", "PHONE", "GPE"):
              if not token_pattern.match(ent.text):
                  violations.append(f"{ent.category} leak detected: {ent.text}")

      is_clean = len(violations) == 0
      report = EgressReport(is_clean=is_clean, violations=violations)
      if not is_clean:
          raise EgressViolationError(
              f"Privacy egress validation failed with {len(violations)} violations.",
              report=report
          )
      return report
  ```

#### Finding M1-03 (High)
- **File**: `backend/app/services/privacy/egress_validator.py`
- **Line(s)**: 43–46
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**:
  `egress_validator` checks `if ent.category in ("ORG", "PERSON", "EMAIL", "PHONE", "GPE"): violations.append(...)`.
  spaCy's NER parser frequently labels uppercase bracket tokens like `[ORG_1]`, `[BANK_1]`, or `[PERSON_1]` as `ORG` or `PERSON` entities.
  Because there is no exclusion check for valid bracket tokens, `EgressValidator` flags properly masked tokens as privacy leaks and raises `EgressViolationError`, blocking 100% of properly masked documents.
- **Correct Pattern / Fix**:
  Filter out entities matching the bracket token pattern `re.compile(r"^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE)_\d+\]$")`.

#### Finding M1-04 (Medium)
- **File**: `backend/app/services/privacy/egress_validator.py`
- **Line(s)**: 30–32
- **Severity**: Medium
- **Category**: Architecture / Performance
- **Description**:
  `EgressValidator.__init__` instantiates a new `NERMasker()` and `BankNameMatcher()`. Instantiating `NERMasker` initializes spaCy and Presidio. When `EgressValidator` is created per-request, it introduces massive latency and memory allocation overhead.
- **Correct Pattern / Fix**:
  Support passing shared `bank_matcher` and `ner_masker` instances via dependency injection or default singleton instances.

---

### 2.3 `backend/app/services/privacy/bank_matcher.py`

#### Finding M1-05 (High)
- **File**: `backend/app/services/privacy/bank_matcher.py`
- **Line(s)**: 38–40
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**:
  Off-by-one span indexing bug. `pyahocorasick.Automaton.iter()` returns `(end_index, value)` where `end_index` is the inclusive index of the last character of the match in `text`.
  `start_index = end_index - len(matched_name) + 1`.
  `bank_matcher.py` outputs `(start_index, end_index, matched_name)`.
  Downstream code (e.g. `masking_pipeline.py:54` `range(span["start"], span["end"])` and Python slice indexing `text[start:end]`) assumes standard half-open intervals `[start, end)` where `end` is `start + len`.
  Because `end_index` is inclusive, `span["end"] - span["start"]` is short by 1 character, leaving the last character of every bank match omitted from covered index ranges.
- **Correct Pattern / Fix**:
  ```python
  def find_matches(self, text: str) -> list[tuple[int, int, str]]:
      matches: list[tuple[int, int, str]] = []
      for end_char_index, matched_name in self._automaton.iter(text):
          end_index = end_char_index + 1  # Convert to exclusive end index
          start_index = end_index - len(matched_name)
          matches.append((start_index, end_index, matched_name))
      return matches
  ```

#### Finding M1-06 (High)
- **File**: `backend/app/services/privacy/bank_matcher.py`
- **Line(s)**: 29–31, 38
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**:
  Case-sensitivity and lack of word boundary boundaries.
  1. `ahocorasick.Automaton()` performs exact char matching. If text contains `"emirates nbd"` or `"adcb"`, but `gcc_bank_names.json` contains `"Emirates NBD"` or `"ADCB"`, the matcher fails to detect the bank name.
  2. Short bank abbreviations in `gcc_bank_names.json` (such as `"FAB"`, `"CBD"`, `"DIB"`, `"UAB"`, `"Citi"`, `"Gulf"`) match substrings inside arbitrary words (e.g., `"FABRIC"`, `"CONFIDENT"`, `"RESPONSIBLE"`, `"Citizens"`, `"Gulfstream"`).
- **Correct Pattern / Fix**:
  Normalize text to lowercase when loading and querying the automaton, and verify word boundaries on matched spans:
  ```python
  def find_matches(self, text: str) -> list[tuple[int, int, str]]:
      matches: list[tuple[int, int, str]] = []
      text_lower = text.lower()
      for end_char_index, original_name in self._automaton.iter(text_lower):
          end_index = end_char_index + 1
          start_index = end_index - len(original_name)
          
          # Word boundary check
          is_start_bound = (start_index == 0 or not text[start_index - 1].isalnum())
          is_end_bound = (end_index == len(text) or not text[end_index].isalnum())
          
          if is_start_bound and is_end_bound:
              matched_text = text[start_index:end_index]
              matches.append((start_index, end_index, matched_text))
      return matches
  ```

#### Finding M1-07 (Low)
- **File**: `backend/app/services/privacy/resources/gcc_bank_names.json`
- **Line(s)**: 36
- **Severity**: Low
- **Category**: Data quality / Broken imports and missing dependencies
- **Description**:
  Typo in bank name entry: `"Barclids"` instead of `"Barclays"`.
- **Correct Pattern / Fix**:
  Fix typo in `gcc_bank_names.json` line 36 to `"Barclays"`.

---

### 2.4 `backend/app/services/privacy/ner_masker.py`

#### Finding M1-08 (High)
- **File**: `backend/app/services/privacy/ner_masker.py`
- **Line(s)**: 46–48
- **Severity**: High
- **Category**: Incorrect API usage vs. latest library docs
- **Description**:
  Synchronous CLI download `spacy.cli.download("en_core_web_lg")` inside `NERMasker.__init__`.
  In production Docker/ECS Fargate containers or server environments with read-only root filesystems or airgapped VPCs, calling `spacy.cli.download` dynamically blocks the thread for minutes, exhausts memory, and fails with `PermissionError` or connection timeouts.
- **Correct Pattern / Fix**:
  Remove dynamic CLI download from application runtime code. Ensure `en_core_web_lg` is installed via setup scripts / Dockerfile, and raise an informative `RuntimeError` if missing at startup:
  ```python
  try:
      self.nlp = spacy.load("en_core_web_lg")
  except OSError as exc:
      raise RuntimeError(
          "spaCy model 'en_core_web_lg' is not installed. "
          "Please install it via 'python -m spacy download en_core_web_lg'."
      ) from exc
  ```

#### Finding M1-09 (Medium)
- **File**: `backend/app/services/privacy/ner_masker.py`
- **Line(s)**: 26–38, 52–59
- **Severity**: Medium
- **Category**: Privacy pipeline logic
- **Description**:
  Incomplete financial protection regex patterns.
  Project guidelines mandate that financial numbers (currencies, ratios, percentages, dates, numbers with commas like `1,250,000`) are NEVER masked.
  Current patterns in `FINANCIAL_PATTERNS`:
  1. Only match 5 currencies (`AED|USD|\$|EUR|GBP`), omitting GCC currencies (`SAR`, `QAR`, `KWD`, `BHD`, `OMR`, `€`, `£`).
  2. Omit plain formatted numbers with commas (`1,250,000` or `10,500.50`) when not preceded by currency symbols.
  3. Omit ISO date formats (`YYYY-MM-DD`, `DD/MM/YYYY`) and quarter references (`Q1 2024`, `2024-Q3`).
- **Correct Pattern / Fix**:
  Expand regex patterns in `FINANCIAL_PATTERNS`:
  ```python
  FINANCIAL_PATTERNS = [
      # GCC & Global Currencies (e.g. AED 15.5M, $2.4B, SAR 500,000)
      re.compile(r"\b(AED|USD|EUR|GBP|SAR|QAR|KWD|BHD|OMR|\$|€|£)\s*\d+([.,]\d+)*\s*(Million|Billion|[KkMmBb])?\b", re.IGNORECASE),
      re.compile(r"\b\d+([.,]\d+)*\s*(AED|USD|EUR|GBP|SAR|QAR|KWD|BHD|OMR|\$|€|£)\b", re.IGNORECASE),
      # Standalone numbers with commas and decimals
      re.compile(r"\b\d{1,3}(,\d{3})+(\.\d+)?\b"),
      # Ratios and percentages
      re.compile(r"\b\d+([.,]\d+)*\s*[%xX]\b"),
      re.compile(r"\b0\.\d+\b"),
      # Dates (FY2024, Q1 2024, 31 December 2023, 2024-12-31, 31/12/2023)
      re.compile(r"\b(FY\d{4}|Q[1-4]\s+\d{4}|\d{4}\s+Q[1-4])\b", re.IGNORECASE),
      re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
      re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
      re.compile(r"\b\d{1,2}\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", re.IGNORECASE),
  ]
  ```

#### Finding M1-10 (Medium)
- **File**: `backend/app/services/privacy/ner_masker.py`
- **Line(s)**: 50, 77–81
- **Severity**: Medium
- **Category**: Incorrect API usage vs. latest library docs
- **Description**:
  Unconfigured `AnalyzerEngine()` loads a duplicate copy of spaCy model.
  By default, `AnalyzerEngine()` creates its own `SpacyNlpEngine` instance that loads `en_core_web_lg` a second time into memory (~800MB - 1GB RAM overhead).
  Additionally, `self.analyzer.analyze` lacks a `score_threshold` parameter, causing low-confidence digit patterns to be misidentified as phone numbers.
- **Correct Pattern / Fix**:
  Configure `AnalyzerEngine` with explicit `score_threshold=0.6` and share or disable redundant NLP engines.

---

### 2.5 `backend/app/services/privacy/entity_registry.py`

#### Finding M1-11 (Medium)
- **File**: `backend/app/services/privacy/entity_registry.py`
- **Line(s)**: 43–57
- **Severity**: Medium
- **Category**: Privacy pipeline logic
- **Description**:
  Sequential `str.replace` in `unmask_text` instead of single-pass regex replacement.
  In lines 53–55:
  ```python
  for token in sorted_tokens:
      if token in unmasked_text:
          unmasked_text = unmasked_text.replace(token, self._reverse[token])
  ```
  If an unmasked entity itself contains a token format or another token name, sequential replacements will corrupt the text.
- **Correct Pattern / Fix**:
  Use atomic single-pass regex substitution with `re.sub`:
  ```python
  def unmask_text(self, masked_text: str) -> str:
      if not self._reverse:
          return masked_text
      sorted_tokens = sorted(self._reverse.keys(), key=len, reverse=True)
      pattern = re.compile("|".join(re.escape(token) for token in sorted_tokens))
      return pattern.sub(lambda match: self._reverse[match.group(0)], masked_text)
  ```

#### Finding M1-12 (Low)
- **File**: `backend/app/services/privacy/entity_registry.py`
- **Line(s)**: 25–41
- **Severity**: Low
- **Category**: Privacy pipeline logic
- **Description**:
  Missing entity whitespace stripping and empty string validation in `mask(entity, category)`.
- **Correct Pattern / Fix**:
  Normalize `entity = entity.strip()` and return `""` if entity is empty.

---

### 2.6 `backend/app/services/chunker.py`

#### Finding M1-13 (Critical)
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 40–55
- **Severity**: Critical
- **Category**: Privacy pipeline logic / Algorithm correctness
- **Description**:
  Broken chunk accumulation logic in `_split_text`.
  In lines 40–55:
  ```python
  for part in parts:
      if current_part:
          combined = current_part + delimiter + part
      else:
          combined = part
          
      if len(combined) > self.chunk_size and delimiters[1:]:
          sub_parts = self._split_text(combined, delimiters[1:])
          final_parts.extend(sub_parts)
          current_part = ""
      else:
          final_parts.append(combined)
          current_part = ""
  ```
  `current_part` is initialized to `""` and immediately reset to `""` on every iteration. `current_part` is NEVER populated with accumulated text.
  Consequently, `_split_text` does not accumulate text up to `chunk_size`. Instead, it emits every single split part as an individual chunk.
- **Correct Pattern / Fix**:
  Accumulate parts into `current_part` until the accumulated length exceeds `chunk_size`:
  ```python
  def _split_text(self, text: str, delimiters: list[str]) -> list[str]:
      if not delimiters:
          return [text] if text else []
      
      delimiter = delimiters[0]
      parts = text.split(delimiter)
      final_parts: list[str] = []
      current_part = ""
      
      for part in parts:
          candidate = f"{current_part}{delimiter}{part}" if current_part else part
          if len(candidate) > self.chunk_size:
              if current_part:
                  final_parts.append(current_part)
                  current_part = part
              else:
                  # Part alone exceeds chunk_size; recurse with finer delimiters
                  if delimiters[1:]:
                      final_parts.extend(self._split_text(part, delimiters[1:]))
                  else:
                      final_parts.append(part)
                  current_part = ""
          else:
              current_part = candidate
              
      if current_part:
          final_parts.append(current_part)
          
      return final_parts
  ```

#### Finding M1-14 (High)
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 12–14, 58–115
- **Severity**: High
- **Category**: Algorithm correctness
- **Description**:
  `overlap` parameter is completely unused.
  `__init__` sets `self.overlap = overlap`, but `self.overlap` is never referenced anywhere in `chunk()` or `_split_text()`. All chunks are generated with 0 overlap.
- **Correct Pattern / Fix**:
  Implement overlap between consecutive chunks by carrying over the trailing `overlap` characters into the next chunk.

#### Finding M1-15 (High)
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 36, 43, 88
- **Severity**: High
- **Category**: Algorithm correctness
- **Description**:
  Splitting on `". "` and `" "` strips periods and spaces from text.
  `text.split(delimiter)` removes the delimiter characters. When `combined` is emitted, the removed periods and spaces are lost, corrupting the text content.
- **Correct Pattern / Fix**:
  Use regex splitting with lookbehind/lookahead or restore delimiters when assembling chunks.

#### Finding M1-16 (Medium)
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 82, 88, 110
- **Severity**: Medium
- **Category**: Algorithm correctness
- **Description**:
  Empty line filtering removes `\n\n` paragraph separation. Line 110 filters out empty lines (`if line.strip(): current_section_text.append(line)`), and line 82 joins lines with single `\n`. `section_content` therefore has no double newlines, making `delims[0] = "\n\n"` completely ineffective.
- **Correct Pattern / Fix**:
  Preserve empty lines in `current_section_text` so paragraph boundaries (`\n\n`) remain intact for semantic splitting.

#### Finding M1-17 (Medium)
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 94, 110–111
- **Severity**: Medium
- **Category**: Algorithm correctness
- **Description**:
  Destruction of Markdown tables.
  Docling generates tables in Markdown format (`| col1 | col2 |`). Individual rows often have fewer than 8 words. Line 94 `if len(rc_clean.split()) >= 8:` silently drops table rows, destroying critical financial metrics and tabular validation data.
- **Correct Pattern / Fix**:
  Detect Markdown table blocks and treat whole tables as atomic chunks that are not subject to the 8-word filter.

---

### 2.7 `backend/app/services/document_extractor.py`

#### Finding M1-18 (Medium)
- **File**: `backend/app/services/document_extractor.py`
- **Line(s)**: 40–47
- **Severity**: Medium
- **Category**: Async/await correctness / Error handling
- **Description**:
  Unhandled Docling conversion exceptions. `self.converter.convert(stream)` can raise runtime errors on corrupted, password-protected, or unreadable PDF/DOCX files. These exceptions bubble up raw internal stack traces.
- **Correct Pattern / Fix**:
  Wrap `self.converter.convert` in a `try...except Exception as exc:` block and raise a custom `DocumentExtractionError`.

#### Finding M1-19 (Low)
- **File**: `backend/app/services/document_extractor.py`
- **Line(s)**: 23–29
- **Severity**: Low
- **Category**: Incorrect API usage vs. latest library docs
- **Description**:
  Missing explicit `WordFormatOption` in `format_options` for `InputFormat.DOCX`.
- **Correct Pattern / Fix**:
  Import `WordFormatOption` from `docling.document_converter` and explicitly configure `format_options={InputFormat.PDF: PdfFormatOption(...), InputFormat.DOCX: WordFormatOption()}`.

---

### 2.8 Cross-Cutting / API Integration

#### Finding M1-20 (High)
- **File**: `backend/app/api/documents.py` (and privacy service instantiations)
- **Line(s)**: 60, 81, 85, 89
- **Severity**: High
- **Category**: Architecture / Performance
- **Description**:
  Heavy NLP model instantiations per upload request. `DocumentExtractor()`, `MaskingPipeline()`, `EgressValidator()`, and `MarkdownChunker()` are instantiated inside the FastAPI endpoint handler on every upload. This causes repeated loading of spaCy models and Presidio engines on every request, leading to massive memory churn and latency spikes.
- **Correct Pattern / Fix**:
  Instantiate singletons at module level or provide them via FastAPI lifespan dependency injection.

#### Finding M1-21 (Low)
- **File**: Multiple files (`entity_registry.py`, `bank_matcher.py`, `ner_masker.py`, `masking_pipeline.py`, `egress_validator.py`, `chunker.py`, `document_extractor.py`)
- **Line(s)**: Multiple
- **Severity**: Low
- **Category**: Type annotation correctness
- **Description**:
  Missing `-> None` return type annotations on `__init__` methods and usage of legacy `typing.List`, `typing.Dict`, `typing.Tuple` instead of Python 3.12 built-in generic collections (`list`, `dict`, `tuple`).
- **Correct Pattern / Fix**:
  Add `-> None` return annotations to all `__init__` methods and replace `typing.List` / `typing.Dict` with built-in generics.

#### Finding M1-22 (Low)
- **File**: `backend/app/services/privacy/__init__.py`
- **Line(s)**: 1
- **Severity**: Low
- **Category**: Code conventions / Architecture
- **Description**:
  `__init__.py` is completely empty and does not expose the public API of the privacy module.
- **Correct Pattern / Fix**:
  Add `from __future__ import annotations` and define `__all__` exporting `EntityRegistry`, `BankNameMatcher`, `NERMasker`, `EntitySpan`, `MaskingPipeline`, `EgressValidator`, `EgressReport`, and `EgressViolationError`.

---

## 3. Dependency & Environment Analysis

Review of `backend/requirements.txt` in relation to Privacy and Document Extraction:
1. **spaCy Model Distribution**: `spacy>=3.7.0` is present, but `en_core_web_lg` is not specified as a direct dependency or wheel URL in `requirements.txt`. A post-install or Dockerfile step `python -m spacy download en_core_web_lg` must be verified.
2. **Unused `presidio-anonymizer`**: `presidio-anonymizer` is listed in `requirements.txt` but never imported anywhere in the backend (the application implements custom anonymization via `EntityRegistry` and `MaskingPipeline`).
3. **Pydantic v2 Extras**: `pydantic[dotenv,email]>=2.0` includes `dotenv` which is deprecated in Pydantic v2 in favor of `pydantic-settings`.

---

## 4. Verification & Testing Recommendations

To verify these findings and fixes once code changes are made:
1. **Masking Roundtrip & Global Replace Test**: Pass a document containing `"May the model succeed"` along with a person named `"May"`, and verify that the verb `"may"` is not converted to `[PERSON_1]`.
2. **Bracket Token Non-Collision Test**: Verify that masking `"BANK"` or `"ORG"` does not corrupt `[BANK_1]` into `[[ORG_2]_1]`.
3. **Egress Validator Token Exemption Test**: Verify that `EgressValidator.validate()` returns `is_clean=True` for properly masked text containing `[BANK_1]`, `[ORG_1]`, `[PERSON_1]`.
4. **Bank Matcher Half-Open Slice Test**: Verify that `text[start:end]` returns the exact full bank name for every match from `BankNameMatcher`.
5. **Chunker Accumulation & Overlap Test**: Verify that a 5,000-character section produces ~3 chunks of ~2,400 characters each with ~400 character overlap, without dropping sentences or Markdown tables.
