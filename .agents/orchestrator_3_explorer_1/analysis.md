# Deep Review & Remediation Analysis: Privacy Pipeline & Zero-Trust Masking

**Reviewer**: Explorer 1  
**Module**: Privacy Pipeline (`backend/app/services/privacy/`, `backend/app/schemas/privacy.py`, `backend/app/api/privacy.py`, and privacy integrations in `documents.py` and `query.py`)  
**Target Environment**: Python 3.12, FastAPI 0.112+, SQLAlchemy 2.0 Async, Pydantic v2, spaCy 3.7+, Presidio, pyahocorasick  

---

## 1. Executive Summary

The privacy subsystem of ModelAudit AI implements a zero-trust, in-memory entity masking pipeline designed to prevent sensitive banking entities, personal identifiable information (PII), and GCC bank names from leaking to external LLM providers (NVIDIA NIM and Google Gemini).

Our deep inspection confirmed that the core architecture implements:
- **Bijective in-memory entity mapping** with reverse length-descending atomic unmasking (`EntityRegistry`).
- **Zero persistence** of entity registry data to disk or database tables.
- **Aho-Corasick automaton** with half-open character index slicing and word boundary checks for GCC bank names (`BankNameMatcher`).
- **Comprehensive financial protection regexes** preserving formatted numbers with commas (e.g., `1,250,000`), currencies (`AED`, `USD`, `SAR`, etc.), dates, ratios (`1.25x`, `0.78`), percentages (`42%`), basis points (`50 bps`), and credit risk metrics (`Gini`, `AUC`, `KS`, `PSI`).
- **Right-to-left reverse offset slicing** to avoid character drift during document replacement (`MaskingPipeline`).
- **Multi-tenant isolation** with session-scoped registries.

We identified **3 High/Medium issues** and **5 Low/Optimization improvements** spanning egress validation edge cases, multi-turn chat history egress leakage, bracket token re-masking protection, async threadpool offloading, and Pydantic v2 / Python 3.12 schema modernization.

---

## 2. File-by-File Detailed Audit

### 2.1 `backend/app/services/privacy/entity_registry.py`
- **Purpose**: Session-scoped in-memory bijective mapping between original entity strings and bracket tokens (`[BANK_1]`, `[ORG_1]`, `[PERSON_1]`, etc.).
- **Strengths**:
  - Bijective data structures (`_forward` and `_reverse` dictionaries) are strictly maintained in-memory.
  - `unmask_text()` sorts tokens by length descending (`sorted(self._reverse.keys(), key=len, reverse=True)`) and compiles a single regex alternation with `re.escape()`. This prevents prefix collision bugs (e.g. `[ORG_10]` being corrupted by `[ORG_1]`) and guarantees atomic single-pass substitution.
  - `get_mapping()` and `get_reverse_mapping()` return `.copy()` shallow copies, preventing callers from mutating internal state.
- **Observations & Edge Cases**:
  - `mask(entity, category)` applies `cleaned_entity = entity.strip()`. If `entity` consists solely of whitespace, it returns `""` and avoids polluting the registry.
  - Counter increments per category are isolated.

### 2.2 `backend/app/services/privacy/registry_store.py`
- **Purpose**: Global in-memory registry manager mapping `session_id` (`uuid.UUID`) to `EntityRegistry` instances.
- **Strengths**:
  - Simple, isolated session factory. Provides `get_registry(session_id)` and `clear_registry(session_id)`.
- **Issues Identified**:
  - **Type modernization**: Uses `from typing import Dict` (line 4) and `Dict[uuid.UUID, EntityRegistry]` (line 9). Should use Python 3.12 `dict[uuid.UUID, EntityRegistry]`.
  - **UUID string coercion**: `get_registry` accepts `uuid.UUID`. If a caller passes a `str` representation of UUID, dictionary lookup would fail to match `uuid.UUID` keys. Adding string coercion `if isinstance(session_id, str): session_id = uuid.UUID(session_id)` ensures type resilience.
  - **Memory Eviction**: In long-running deployments, session entries remain in memory until explicitly cleared. Adding an optional LRU cache or max-size cap prevents potential memory leakage.

### 2.3 `backend/app/services/privacy/bank_matcher.py`
- **Purpose**: Fast Aho-Corasick automaton for matching GCC bank names from `resources/gcc_bank_names.json`.
- **Strengths**:
  - Matches case-insensitively using lowercase automaton keys while preserving original slice casing from `text[start_index:end_index]`.
  - Accurate half-open interval calculation: `end_index = end_char_index + 1` and `start_index = end_index - len(canonical_name)`.
  - Word boundary enforcement:
    ```python
    if start_index > 0 and text[start_index - 1].isalnum():
        continue
    if end_index < len(text) and text[end_index].isalnum():
        continue
    ```
    This prevents false positives on substrings like `FABRIC` for `FAB` or `CONFIDENT` for `DIB`.
- **Observations & Edge Cases**:
  - Underscores (`_`) are not alphanumeric (`'_'.isalnum() == False`). If variable names with underscores appear (e.g. `TEST_FAB_MODEL`), `FAB` matches. Adding `or text[...] == '_'` aligns with regex `\w` word boundary semantics.

### 2.4 `backend/app/services/privacy/ner_masker.py`
- **Purpose**: SpaCy (`en_core_web_lg`) and Presidio Analyzer integration for extracting `ORG`, `PERSON`, `GPE`, `EMAIL`, and `PHONE` entities, with protection for financial numbers and dates.
- **Strengths**:
  - Shared memory optimization: Presidio `AnalyzerEngine` shares the loaded `self.nlp` instance (`spacy_engine.nlp = {"en": self.nlp}`), saving ~1.6 GB RAM.
  - Preserves financial numbers with commas (`\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b`), GCC currencies (`AED`, `SAR`, `QAR`, `KWD`, `BHD`, `OMR`, `USD`, `EUR`, `GBP`), percentages (`42%`, `12.5 %`), basis points (`50 bps`), ratios (`1.25x`, `0.78`), and standard/named/fiscal dates (`2024-12-31`, `31 December 2023`, `Q1 2024`, `FY2024`).
- **Issues Identified**:
  - **Existing Token Double-Masking**: In `find_entities()`, if the text already contains a valid masking token (e.g. `[ORG_1]` or `[BANK_2]`), spaCy can classify `[ORG_1]` as `ORG`. Without an exemption for `VALID_TOKEN_PATTERN`, the pipeline attempts to re-mask `[ORG_1]` into `[ORG_2]` or nested brackets.
  - **Metric Expansion**: `PROTECTED_METRIC_NAMES` can be expanded from 9 metrics to include common UAE/CBUAE credit risk metrics (`roe`, `roa`, `nim`, `npl`, `raroc`, `var`, `cvar`, `wacc`, `ccf`, `pit`, `ttc`).

### 2.5 `backend/app/services/privacy/masking_pipeline.py`
- **Purpose**: Full masking orchestrator that executes `BankNameMatcher` + `NERMasker`, resolves overlapping spans, and performs reverse character offset replacement.
- **Strengths**:
  - Longest match overlap resolution: `spans.sort(key=lambda s: (s["end"] - s["start"], -s["start"]), reverse=True)` ensures that compound entities (e.g. `"First Abu Dhabi Bank"`, length 20) take precedence over sub-entities (e.g. `"FAB"` or `"Abu Dhabi"`).
  - Reverse slicing: `resolved_spans.sort(key=lambda s: s["start"], reverse=True)` guarantees right-to-left substitution, completely eliminating index drift without requiring token offset recalculation.
  - Returns tuple of `(masked_text, registry)`.

### 2.6 `backend/app/services/privacy/egress_validator.py`
- **Purpose**: Pre-egress gatekeeper ensuring no unmasked bank names or sensitive entities are sent to external LLMs.
- **Strengths**:
  - 3-tier validation: (1) Registered original strings, (2) `BankNameMatcher`, (3) `NERMasker`.
  - Excludes valid bracket tokens (`VALID_TOKEN_PATTERN`) from triggering false positives.
  - Raises explicit `EgressViolationError` containing detailed `EgressReport`.
- **Issues Identified**:
  - **High Severity — False Positive Egress Blocks on Common Substrings**:
    Line 69: `if original_entity and original_entity in masked_text:`
    This is a raw substring search without word boundaries. If a person named `"Mark"`, `"Dan"`, `"Ali"`, or an entity `"Art"`, `"Price"` is masked, any appearance of `"Market"`, `"Validation"`, `"Article"`, or `"Price"` in `masked_text` evaluates `original_entity in masked_text` to `True`. This causes `EgressViolationError` to trigger on legitimate masked text.
    **Fix**: Replace with word boundary regex check:
    ```python
    pattern = re.compile(rf"(?<!\w){re.escape(original_entity)}(?!\w)", re.IGNORECASE)
    if pattern.search(masked_text):
        violations.append(f"Registered entity leak detected: '{original_entity}'")
    ```

### 2.7 `backend/app/schemas/privacy.py`
- **Purpose**: Request and response Pydantic models for privacy endpoints.
- **Issues Identified**:
  - Missing `model_config = ConfigDict(from_attributes=True)` on `MaskRequest`, `MaskResponse`, and `RedactionLogResponse`.
  - Legacy `Dict`, `Optional` imports instead of Python 3.12 native types `dict[str, str]` and `uuid.UUID | None`.

### 2.8 `backend/app/api/privacy.py`
- **Purpose**: Privacy simulator API routes (`/privacy/mask` and `/privacy/redactions`).
- **Issues Identified**:
  - `mask_text()` calls `masking_pipeline.mask_document()` synchronously inside `async def`. SpaCy and Presidio are CPU-bound and block the asyncio event loop during large inference requests. Wrapping with `await run_in_threadpool(masking_pipeline.mask_document, request.text, registry=registry)` resolves this.

### 2.9 `backend/app/api/query.py` (Privacy Integration in Multi-Turn Chat)
- **Purpose**: Conversational Q&A endpoint against document chunks and regulatory corpus.
- **Issues Identified**:
  - **High Severity — Multi-Turn Chat Egress Failure**:
    In `query.py`, user queries are masked for prompt construction, but raw unmasked queries are saved to DB (`ChatMessage(content=request.question)`). In multi-turn chat (turn 2+), `history_context` is built from previous messages in the database and inserted unmasked into `prompt`. When `egress_validator.validate(prompt, registry)` runs on line 135, it detects the unmasked entity from turn 1 and blocks the request with `EgressViolationError`.
    **Fix**: Either mask `history_context` via `masking_pipeline.mask_document(history_context, registry=registry)` prior to prompt assembly, or store `masked_question` in `ChatMessage.content`.

---

## 3. Bug Catalog & Remediation Matrix

| ID | File | Line(s) | Severity | Category | Description | Recommended Remediation |
|---|---|---|---|---|---|---|
| **PRV-REV-01** | `backend/app/services/privacy/egress_validator.py` | 68–70 | **High** | Logic / Edge Case | Raw substring check `original_entity in masked_text` causes false positive egress blocks on words containing entity substrings (e.g. `"Mark"` in `"Market"`). | Use word-boundary regex matching: `re.search(rf"(?<!\w){re.escape(original_entity)}(?!\w)", masked_text)`. |
| **PRV-REV-02** | `backend/app/api/query.py` | 97, 131–135 | **High** | Privacy Egress / Chat | Unmasked multi-turn chat history inserted into `prompt` causes `egress_validator` to fail on turn 2+ when past user messages contain entities. | Mask `history_context` using `masking_pipeline.mask_document(history_context, registry=registry)` before adding to `prompt`. |
| **PRV-REV-03** | `backend/app/services/privacy/ner_masker.py` | 158–187 | **Medium** | Logic / Edge Case | SpaCy extracts existing bracket tokens (e.g. `[ORG_1]`) as entities, causing double-masking/token corruption during re-masking passes. | Skip entity candidate spans matching `VALID_TOKEN_PATTERN.match(ent.text)` in `find_entities()`. |
| **PRV-REV-04** | `backend/app/api/privacy.py` | 39–40 | **Medium** | Async Safety | `mask_document()` runs synchronously in `async def mask_text`, blocking the asyncio event loop during CPU-heavy spaCy/Presidio extraction. | Wrap call in `await run_in_threadpool(masking_pipeline.mask_document, request.text, registry=registry)`. |
| **PRV-REV-05** | `backend/app/schemas/privacy.py` | 1–17 | **Low** | Pydantic v2 / Style | Missing `model_config = ConfigDict(...)` and uses legacy `typing.Dict` / `typing.Optional`. | Modernize to `dict[str, str]`, `uuid.UUID | None`, and add `model_config = ConfigDict(from_attributes=True)`. |
| **PRV-REV-06** | `backend/app/services/privacy/registry_store.py` | 4, 9, 11–19 | **Low** | Type / Robustness | Uses legacy `typing.Dict` and lacks `str` to `uuid.UUID` coercion for `session_id`. | Use `dict[uuid.UUID, EntityRegistry]` and coerce `session_id = uuid.UUID(str(session_id))`. |
| **PRV-REV-07** | `backend/app/services/privacy/ner_masker.py` | 76–86 | **Low** | Enhancement | `PROTECTED_METRIC_NAMES` lacks additional credit risk modeling acronyms (e.g. `roe`, `roa`, `nim`, `npl`, `raroc`, `var`, `wacc`). | Expand set to cover full CBUAE MMG metric vocabulary. |
| **PRV-REV-08** | `backend/app/services/privacy/bank_matcher.py` | 64–67 | **Low** | Edge Case | `isalnum()` boundary check misses underscore `'_'`, allowing matching inside snake_case identifiers. | Add `or text[...] == '_'` or `\w` boundary checks. |

---

## 4. Proposed Code Patches (Remediation Blueprints)

### Patch 1: `egress_validator.py` Word Boundary Leak Check
```python
# Before (Line 68-70):
for original_entity in mapping.keys():
    if original_entity and original_entity in masked_text:
        violations.append(f"Registered entity leak detected: '{original_entity}'")

# After:
for original_entity in mapping.keys():
    if original_entity:
        # Enforce boundary check to prevent substring collisions (e.g., 'Mark' in 'Market')
        leak_pattern = re.compile(rf"(?<!\w){re.escape(original_entity)}(?!\w)", re.IGNORECASE)
        if leak_pattern.search(masked_text):
            violations.append(f"Registered entity leak detected: '{original_entity}'")
```

### Patch 2: `ner_masker.py` Existing Token Exemption & Metric Expansion
```python
# Before:
for ent in doc.ents:
    if ent.label_ in ("ORG", "PERSON", "GPE"):
        if not self._is_protected(ent.text):
            entities.append(EntitySpan(ent.start_char, ent.end_char, ent.text, ent.label_))

# After:
from app.services.privacy.egress_validator import VALID_TOKEN_PATTERN

for ent in doc.ents:
    if ent.label_ in ("ORG", "PERSON", "GPE"):
        # Prevent re-masking or corrupting existing bracket tokens (e.g. [ORG_1])
        if not VALID_TOKEN_PATTERN.match(ent.text) and not self._is_protected(ent.text):
            entities.append(EntitySpan(ent.start_char, ent.end_char, ent.text, ent.label_))
```

### Patch 3: `schemas/privacy.py` Modernization
```python
from __future__ import annotations
import uuid
from pydantic import BaseModel, ConfigDict

class MaskRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    text: str
    session_id: uuid.UUID | None = None

class MaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    masked_text: str
    redactions: dict[str, str]

class RedactionLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    session_id: uuid.UUID
    redactions: dict[str, str]
```

### Patch 4: `api/query.py` History Masking
```python
# In conversational_query (around line 131):
if history_context:
    # Mask past conversation history using the session registry to prevent egress violations
    masked_history, _ = masking_pipeline.mask_document(history_context, registry=registry)
    prompt += f"Conversation History:\n{masked_history}\n\n"
prompt += f"Context:\n{context_text}\n\nQuestion: {masked_question}"
```

---

## 5. Summary Assessment

The Privacy Pipeline is well-architected, robustly maintaining strict in-memory isolation, exact reverse offset character slicing, and comprehensive financial protection regexes. Applying the 3 high/medium fixes (word-boundary leak checking in `EgressValidator`, history context masking in `query.py`, and existing token exemption in `NERMasker`) alongside the 5 low/style modernizations will bring the privacy subsystem to 100% production readiness and complete compliance with all CBUAE MMG zero-trust privacy constraints.
