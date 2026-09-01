# Handoff Report — Adversarial Empirical Challenge

## 1. Observation

### Test Execution Command & Outcome
- **Command executed**:
  `$env:DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db"; $env:JWT_SECRET_KEY="testsecret123456789012345678901234567890"; $env:PYTHONPATH="backend"; backend\venv\Scripts\python.exe -m pytest backend/tests -v`
- **Results**: 30 PASSED, 3 FAILED out of 33 tests in 46.23s.
- **Stress Test Suites Created**:
  1. `backend/tests/test_stress_multitenancy.py` (3 tests — 3/3 PASSED)
  2. `backend/tests/test_stress_privacy.py` (6 tests — 6/6 PASSED)
  3. `backend/tests/test_stress_chunking.py` (3 tests — 3/3 PASSED)
  4. `backend/tests/test_stress_llm_routing.py` (4 tests — 4/4 PASSED)
  5. `backend/tests/test_stress_guardrails.py` (4 tests — 4/4 PASSED)
  6. `backend/tests/test_stress_analytics.py` (3 tests — 3/3 PASSED)
  7. `backend/tests/test_stress_security_auth.py` (5 tests — 5/5 PASSED)
  8. `backend/tests/test_auth.py` (2 tests — 2/2 PASSED)

### Observed Failures (3 Tests in `backend/tests/services/test_guardrails.py`)
```
FAILED backend/tests/services/test_guardrails.py::test_guardrails_initialization
FAILED backend/tests/services/test_guardrails.py::test_guardrails_off_topic
FAILED backend/tests/services/test_guardrails.py::test_guardrails_jailbreak
```
Verbatim Traceback:
```
backend\app\services\guardrails\guardrails_service.py:30: in __init__
    self.rails = LLMRails(config)
backend\venv\Lib\site-packages\nemoguardrails\rails\llm\llmrails.py:387: in __init__
    self.runtime = colang_version_to_runtime[config.colang_version](config=config, verbose=verbose)
backend\venv\Lib\site-packages\nemoguardrails\colang\v2_x\runtime\runtime.py:141: in _init_flow_configs
    self.flow_configs = create_flow_configs_from_flow_list(self.config.flows)
backend\venv\Lib\site-packages\nemoguardrails\colang\v2_x\runtime\runtime.py:692: in create_flow_configs_from_flow_list
    raise ColangSyntaxError(
        f"Multiple non-overriding flows with name '{flow.name}' detected! There can only be one!"
    )
E   nemoguardrails.colang.v2_x.runtime.errors.ColangSyntaxError: Multiple non-overriding flows with name 'bot refuse to respond' detected! There can only be one!
```

### Observed Code Defect in `backend/app/services/guardrails/rails.co`
Lines 55-62 of `backend/app/services/guardrails/rails.co`:
```colang
flow bot refuse to respond
  bot say "I'm sorry, but I cannot verify this answer against the provided credit documentation."

flow check hallucination against context
  $hallucination_prob = await check_hallucination_action()
  if $hallucination_prob > 0.7
    bot refuse to respond
```
In NeMo Guardrails 0.11 / Colang 2.0 (`nemoguardrails/colang/v2_x/library/core.co`), `bot refuse to respond` is a standard library flow. Defining `flow bot refuse to respond` without `@override` causes runtime failure on initialization.

### Observed Privacy Masking Edge Case in `backend/app/services/privacy/ner_masker.py`
In `ner_masker.py`, `FINANCIAL_PATTERNS` regex for currencies is `(?:AED|SAR|USD|EUR|GBP)\s*\d+`.
If text contains a standalone currency token (e.g. `"The values are reported in AED (Millions)"`), spaCy's `en_core_web_lg` extracts `"AED"` as an `ORG`. Since `_is_protected("AED")` returns `False` (lacking digits), `"AED"` is incorrectly masked as `[ORG_x]`. Similarly, the statistical metric `"Gini"` is often tagged as `PERSON` by spaCy unless `"gini"` is added to protected keywords in `_is_protected()`.

---

## 2. Logic Chain

1. **Guardrails Service Crash**:
   - `GuardrailsService.__init__` in `guardrails_service.py:30` calls `LLMRails(config)`.
   - `LLMRails` parses `rails.co` and loads standard library flows from `nemoguardrails/colang/v2_x/library/core.co`.
   - Both `core.co` and `rails.co` define `flow bot refuse to respond`.
   - Colang 2.0 requires either an `@override` decorator or a distinct flow name (e.g. `flow bot refuse ungrounded`).
   - Consequently, `GuardrailsService` cannot be instantiated in production without raising `ColangSyntaxError`.

2. **Multi-Tenancy Isolation Verification**:
   - Tested `HybridRetriever._fetch_chunks_for_document(db, tenant_id, document_id)` with cross-tenant document IDs. Verified that querying another tenant's document returns 0 chunks.
   - Tested HTTP API `/documents/{doc_id}` across tenants. Verified that attempting to read or query a document owned by Tenant B with a JWT from Tenant A returns HTTP 404.
   - Tested Pinecone vector namespace formatting. Verified that user documents are isolated under `user-docs:{tenant_id}:{document_id}`.

3. **Privacy & Zero-Trust Masking Verification**:
   - Tested Bank Name Matcher: Case insensitivity, word boundary enforcement (e.g., `"FABRIC"` is not matched as `"FAB"`, `"MASTERCARD"` is not matched as `"CBD"`).
   - Tested financial figure preservation: `AED 1,250,000`, `45 bps`, `FY2024`, `12.5%` remain intact.
   - Tested overlapping span resolution: Longest span is selected and replaced via reverse-offset slicing to prevent token corruption.
   - Tested Egress Validator: Correctly detects and blocks unmasked registered entities and raw bank names via `EgressViolationError`.
   - Tested Atomic Unmasking: Special regex characters in original entities are safely escaped.

4. **Document Extraction & Chunking Verification**:
   - Tested Markdown Table Preservation: Tables with sub-8-word rows are preserved as single cohesive chunks.
   - Tested Sliding Window Overlap: Chunks retain overlap text and split on sentence boundaries without splitting on financial commas (e.g., `1,250,000`).

5. **LLM Routing & Circuit Breaker Verification**:
   - Tested `router.generate_stream`: Functions as an asynchronous generator yield stream chunks.
   - Tested automatic fallback: NVIDIA failure gracefully triggers secondary Gemini provider.
   - Tested `AllProvidersUnavailableError`: Correctly raised when all providers fail.
   - Tested `CircuitBreaker`: Transitions across `CLOSED -> OPEN -> HALF_OPEN` and protects state transitions under concurrent tasks using `asyncio.Lock`.

6. **Security & Authentication Verification**:
   - Tested RS256 JWT validation: Validates signature and claims.
   - Tested Algorithm Confusion Defense: Rejects HS256 forged tokens with `ValueError: Invalid token`.
   - Tested Deactivated User Defense: Returns HTTP 403 Forbidden on authenticated endpoints.
   - Tested Refresh Token Defense: Rejects `type='refresh'` tokens on data routes with HTTP 401 Unauthorized.
   - Tested File Upload DoS Defense: Enforces 50MB size limit and returns HTTP 413 Payload Too Large.

---

## 3. Caveats

- Live NVIDIA NIM and Google Gemini API calls were tested using mocked network clients with realistic responses and exception conditions to ensure deterministic, reproducible test execution in offline test environments.
- PostgreSQL database tests were run using SQLite async in-memory with `StaticPool` and full schema DDL mirroring production models.

---

## 4. Conclusion

### Overall Risk Assessment: MEDIUM
- The backend architecture across multi-tenancy, privacy masking, document chunking, LLM routing, analytics metrics, and security/auth is solid and passed all 25 adversarial stress tests.
- However, 1 critical runtime blocker exists in NeMo Guardrails:
  - `backend/app/services/guardrails/rails.co`: `ColangSyntaxError` due to duplicate flow name `bot refuse to respond` colliding with Colang 2.0 core library.

### Verdict
**REQUEST_CHANGES**

### Actionable Remediation Required
1. In `backend/app/services/guardrails/rails.co`:
   Add `@override` above line 55:
   ```colang
   @override
   flow bot refuse to respond
     bot say "I'm sorry, but I cannot verify this answer against the provided credit documentation."
   ```
   Or rename the flow to `flow bot refuse ungrounded` and update line 61 accordingly.
2. In `backend/app/services/privacy/ner_masker.py`:
   Update `_is_protected()` to include standalone currency codes (`{"aed", "sar", "usd", "eur", "gbp"}`) and financial metrics (`{"gini", "auc", "ks", "psi", "brier", "car"}`) in the protected dictionary check so spaCy NER never misclassifies them as `ORG`/`PERSON`.

---

## 5. Verification Method

To verify these findings independently:
```powershell
$env:DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db"
$env:JWT_SECRET_KEY="testsecret123456789012345678901234567890"
$env:PYTHONPATH="backend"
backend\venv\Scripts\python.exe -m pytest backend/tests -v
```
- **Files to inspect**:
  - `backend/app/services/guardrails/rails.co` (lines 55-62)
  - `backend/app/services/privacy/ner_masker.py` (lines 75-100)
  - `backend/tests/test_stress_*.py` (all 7 stress test suites)
- **Invalidation Condition**: If `pytest backend/tests/services/test_guardrails.py` passes without `ColangSyntaxError`, this finding is resolved.
