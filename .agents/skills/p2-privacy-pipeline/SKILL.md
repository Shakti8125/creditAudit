---
name: p2-privacy-pipeline
description: >-
  Use this skill to build the complete zero-trust privacy masking pipeline for ModelAudit AI. This includes building the entity registry, bank matcher, NER masker, masking pipeline, and egress validator.
---

# Zero-Trust Privacy Masking Pipeline

Follow these detailed steps to build the complete privacy pipeline for Phase 2.

## Step 1: Entity Registry (`backend/app/services/privacy/entity_registry.py`)

Create `backend/app/services/privacy/entity_registry.py`.

Implement the `EntityRegistry` class:
- This is an in-memory bijective mapping (session-scoped, NEVER persisted to disk or DB).
- Properties:
  - `_forward: dict[str, str]` (maps entity string to token, e.g., 'Emirates NBD' -> '[BANK_1]')
  - `_reverse: dict[str, str]` (maps token to entity)
  - `_counters: dict[str, int]` (keeps track of next IDs for each category)
- Categories supported: `BANK`, `ORG`, `PERSON`, `EMAIL`, `PHONE`.
- Method `mask(entity: str, category: str) -> str`: Returns existing token if entity exists, else creates a new one (e.g., `[BANK_1]`).
- Method `unmask_text(masked_text: str) -> str`: Replaces tokens with original entities. MUST do length-descending regex replacement to avoid prefix collisions (e.g., replacing `[ORG_10]` before `[ORG_1]`).
- Method `get_mapping() -> dict[str, str]`: Returns the forward mapping for the masking inspector UI.

## Step 2: Bank Matcher (`backend/app/services/privacy/bank_matcher.py`)

Create `backend/app/services/privacy/bank_matcher.py`.

Implement the `BankNameMatcher` class:
- Uses `ahocorasick.Automaton()` for O(n) multi-pattern matching.
- `__init__` loads ~200+ GCC/global bank names from a JSON resource file.
- The resource file should be located at: `backend/app/services/privacy/resources/gcc_bank_names.json`.
- Must match both abbreviations and full names.
- Method `find_matches(text: str) -> list[tuple[int, int, str]]`: Returns a list of `(start_index, end_index, matched_name)`.

*Note: Check `references/bank-names-spec.md` for a comprehensive list of banks.*

## Step 3: NER Masker (`backend/app/services/privacy/ner_masker.py`)

Create `backend/app/services/privacy/ner_masker.py`.

Implement the `NERMasker` class:
- Integrates spaCy and Presidio AnalyzerEngine.
- Loads the `en_core_web_lg` spaCy model at startup.
- Extracts `ORG`, `PERSON`, `GPE` entities via spaCy.
- Extracts `EMAIL_ADDRESS`, `PHONE_NUMBER` via Presidio.
- **CRITICAL RULE**: Financial number protection regex. DO NOT MASK:
  - Currency amounts: `AED 15.5 Million`, `$2.4B`, `USD 10,000,000`
  - Ratios: `1.25x`, `42%`, `0.78`
  - Dates: `FY2024`, `31 December 2023`
- Method `find_entities(text: str) -> list[EntitySpan]`: Where `EntitySpan` holds `(start, end, text, category)`.

## Step 4: Masking Pipeline (`backend/app/services/privacy/masking_pipeline.py`)

Create `backend/app/services/privacy/masking_pipeline.py`.

Implement the `MaskingPipeline` class:
- Orchestrates the full masking flow.
- Method `mask_document(raw_text: str) -> tuple[str, EntityRegistry]`:
  1. Run `BankNameMatcher` to collect bank spans.
  2. Run `NERMasker` to collect entity spans.
  3. Merge all spans, resolving overlaps by choosing the longest match first.
  4. Sort the distinct matched text by length descending (to mask longer strings before their substrings).
  5. Register each in `EntityRegistry` and retrieve their respective tokens.
  6. Replace all spans in the text with their assigned tokens.
  7. Return `(masked_text, registry)`.

## Step 5: Egress Validator (`backend/app/services/privacy/egress_validator.py`)

Create `backend/app/services/privacy/egress_validator.py`.

Implement the `EgressValidator` class:
- Validates that no unmasked entities leak to the LLM.
- Method `validate(masked_text: str, registry: EntityRegistry) -> EgressReport`:
  1. Re-run `BankNameMatcher` on the masked text (should find 0 matches).
  2. Re-run `NERMasker` on the masked text (should find 0 ORG/PERSON/EMAIL/PHONE entities).
  3. If any leak is detected, return `EgressReport(is_clean=False, violations=[...])`.
  4. If clean, return `EgressReport(is_clean=True, violations=[])`.
- **CRITICAL**: If the report is not clean, the request MUST be blocked by raising an `EgressViolationError`.

## Verification

To verify the pipeline works correctly:
1. Test with documents containing UAE bank names, person names, and financial numbers.
2. Assert 0% entity leak rate.
3. Assert 100% financial number preservation.
4. Verify the Egress Validator catches any remaining leaks.
5. Verify `unmask_text` correctly restores all entities, specifically checking for prefix collisions (`[ORG_1]` vs `[ORG_10]`).
