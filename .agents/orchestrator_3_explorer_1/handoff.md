# Handoff Report: Privacy Pipeline & Zero-Trust Masking

**Agent**: explorer_1  
**Working Directory**: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\orchestrator_3_explorer_1`  
**Parent Orchestrator Conv ID**: `dc1f9f40-04a3-458b-8ba8-c612821dd31f`  
**Date**: 2026-08-29T18:05:00Z  
**Type**: Hard Handoff (Investigation Complete)  

---

## 1. Observation

Direct inspection of all source files in the privacy subsystem (`backend/app/services/privacy/`, `backend/app/schemas/privacy.py`, `backend/app/api/privacy.py`, and callers in `documents.py` and `query.py`) revealed the following exact code structures and patterns:

1. **`backend/app/services/privacy/egress_validator.py` (Lines 68–70)**:
   ```python
   # 1. Check registered original entity strings from registry mapping (PRV-02)
   if registry is not None:
       mapping = registry.get_mapping()
       for original_entity in mapping.keys():
           if original_entity and original_entity in masked_text:
               violations.append(f"Registered entity leak detected: '{original_entity}'")
   ```
   *Observation*: `original_entity in masked_text` performs a raw substring containment check without word boundary delimiters.

2. **`backend/app/services/privacy/ner_masker.py` (Lines 155–167, 176–187)**:
   ```python
   # 1. Extract ORG, PERSON, GPE via spaCy
   doc = self.nlp(text)
   for ent in doc.ents:
       if ent.label_ in ("ORG", "PERSON", "GPE"):
           if not self._is_protected(ent.text):
               entities.append(EntitySpan(ent.start_char, ent.end_char, ent.text, ent.label_))
   ```
   *Observation*: `ent.text` is not checked against `VALID_TOKEN_PATTERN = re.compile(r"^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]$")`. If `[ORG_1]` is present in input text, spaCy extracts it as an `ORG`, leading to re-masking / nested brackets.

3. **`backend/app/api/query.py` (Lines 82–88, 91–98, 131–135)**:
   ```python
   user_message = ChatMessage(session_id=session_id, role=ChatRoleEnum.USER, content=request.question)
   ...
   history_context = "\n".join([f"{msg.role.value.capitalize()}: {msg.content}" for msg in history[:-1]])
   ...
   prompt = ""
   if history_context:
       prompt += f"Conversation History:\n{history_context}\n\n"
   prompt += f"Context:\n{context_text}\n\nQuestion: {masked_question}"
   egress_validator.validate(prompt, registry)
   ```
   *Observation*: `history_context` contains raw unmasked user queries from previous turns and is appended to `prompt` without running through `masking_pipeline.mask_document(history_context, registry=registry)`.

4. **`backend/app/api/privacy.py` (Lines 39–40)**:
   ```python
   masking_pipeline = MaskingPipeline()
   masked_text, result_registry = masking_pipeline.mask_document(request.text, registry=registry)
   ```
   *Observation*: `mask_document` is invoked synchronously on the main asyncio thread inside `async def mask_text`.

5. **`backend/app/schemas/privacy.py` (Lines 1–17)**:
   ```python
   from typing import Dict, Optional
   class MaskRequest(BaseModel):
       text: str
       session_id: Optional[uuid.UUID] = None
   ```
   *Observation*: Missing `model_config = ConfigDict(from_attributes=True)` and uses legacy `Dict` / `Optional` types.

6. **`backend/app/services/privacy/registry_store.py` (Lines 4, 9, 11–19)**:
   ```python
   from typing import Dict
   _store: Dict[uuid.UUID, EntityRegistry] = {}
   ```
   *Observation*: Uses `from typing import Dict` and does not coerce string `session_id` to `uuid.UUID`.

7. **`backend/app/services/privacy/ner_masker.py` (Lines 76–86)**:
   *Observation*: `PROTECTED_METRIC_NAMES` contains 9 metrics (`gini`, `auc`, `ks`, `psi`, `brier`, `car`, `ead`, `lgd`, `pd`), but omits other common CBUAE MMG metrics (`roe`, `roa`, `nim`, `npl`, `raroc`, `var`, `cvar`, `wacc`, `ccf`, `pit`, `ttc`).

8. **`backend/app/services/privacy/bank_matcher.py` (Lines 64–67)**:
   *Observation*: Word boundary check checks `text[start_index - 1].isalnum()`, where `'_'.isalnum() == False`.

---

## 2. Logic Chain

1. **Egress False Positive Analysis (Observation 1)**:
   - When a person named `"Mark"` or an entity `"Art"` is registered, `mapping.keys()` contains `"Mark"`.
   - In a model document containing `"Market risk analysis"`, `"Mark" in "Market risk analysis"` evaluates to `True`.
   - `EgressValidator` appends `"Registered entity leak detected: 'Mark'"` and raises `EgressViolationError`.
   - Therefore, raw substring matching must be replaced with word-boundary regex matching `(?<!\w){re.escape(entity)}(?!\w)` to eliminate false-positive rejections.

2. **Multi-Turn Chat History Egress Failure (Observation 3)**:
   - In Turn 1, user asks `"What is the exposure of First Abu Dhabi Bank?"`.
   - Turn 1 question is masked for the immediate LLM call, but saved in plaintext to `ChatMessage.content`.
   - In Turn 2, `history_context` includes `"User: What is the exposure of First Abu Dhabi Bank?"`.
   - `prompt` includes `history_context` without masking.
   - `EgressValidator.validate(prompt, registry)` checks the whole `prompt`, finds `"First Abu Dhabi Bank"`, and triggers `EgressViolationError`.
   - Therefore, `history_context` must be masked using `masking_pipeline.mask_document(history_context, registry=registry)` before adding to `prompt`.

3. **Existing Token Double-Masking (Observation 2)**:
   - SpaCy processes text tokens based on capitalization and grammar. Valid tokens like `[ORG_1]` or `[BANK_2]` are often tagged as `ORG`.
   - Because `_is_protected("[ORG_1]")` is `False`, `NERMasker` extracts it as an entity span.
   - `MaskingPipeline` calls `registry.mask("[ORG_1]", "ORG")`, creating a redundant token `[ORG_2]` or nested brackets `[[ORG_2]]`.
   - Therefore, `find_entities()` must skip spans matching `VALID_TOKEN_PATTERN`.

4. **Async Event Loop Blocking (Observation 4)**:
   - SpaCy model inference (`self.nlp(text)`) and Presidio analysis are CPU-bound operations.
   - Calling `mask_document` directly within `async def mask_text` in `api/privacy.py` blocks the event loop.
   - Offloading via `await run_in_threadpool(masking_pipeline.mask_document, ...)` ensures non-blocking async execution.

5. **Pydantic v2 & Python 3.12 Alignment (Observations 5 & 6)**:
   - `AGENTS.md` mandates `model_config = ConfigDict(...)` for all Pydantic schemas.
   - Python 3.12 native types (`dict[str, str]`, `uuid.UUID | None`) should replace `typing.Dict` and `typing.Optional`.

---

## 3. Caveats

- **External Model Dependencies**: `NERMasker` relies on the installed spaCy model `en_core_web_lg`. If the model is not downloaded in the environment, `NERMasker.__init__` raises `RuntimeError` instructing the user to download it (`python -m spacy download en_core_web_lg`).
- **No Direct Source Changes**: As an explorer agent in read-only audit mode, no backend source files have been directly edited. All remediations are detailed in `analysis.md` and this handoff.

---

## 4. Conclusion

The Privacy Pipeline has a robust zero-trust architecture featuring:
- Bijective, in-memory, session-scoped token mapping.
- Right-to-left reverse offset slicing preventing index drift.
- Full preservation of financial figures, comma-formatted numbers, currencies, and dates.
- Zero persistence of entity registries to disk or database tables.

The 3 key remediations required are:
1. Fix `EgressValidator` registered entity leak detection by using word-boundary regexes instead of raw substring matching.
2. Ensure multi-turn chat in `query.py` masks `history_context` with the session registry before running egress validation.
3. Exclude existing valid bracket tokens (`VALID_TOKEN_PATTERN`) from `NERMasker` entity extraction to avoid re-masking / double-bracket corruption.

---

## 5. Verification Method

To independently verify after remediation:

1. **Unit & Stress Tests**:
   Run the privacy stress test suite:
   ```powershell
   pytest backend/tests/test_stress_privacy.py -v
   ```
2. **Sub-string Word Boundary Verification**:
   Verify that a registered entity `"Mark"` or `"Dan"` in a registry does NOT trigger `EgressViolationError` when `masked_text` contains `"Market risk model for [ORG_1]"`.
3. **Multi-Turn Chat History Verification**:
   Run a two-turn chat flow where Turn 1 mentions a real bank name (`"First Abu Dhabi Bank"`), and verify that Turn 2 passes `EgressValidator.validate(prompt, registry)` without raising `EgressViolationError`.
4. **Token Preservation Verification**:
   Run `mask_document("[ORG_1] and [BANK_1] approved the loan.")` through `MaskingPipeline` and verify that the output remains `"[ORG_1] and [BANK_1] approved the loan."` without nested brackets like `"[[ORG_2]]"`.
5. **Python 3.12 Compilation**:
   ```powershell
   python -m py_compile backend/app/services/privacy/*.py backend/app/schemas/privacy.py backend/app/api/privacy.py
   ```
