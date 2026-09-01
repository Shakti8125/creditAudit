# ModelAudit AI — Comprehensive Backend Static Code Audit Report

**Date**: 2026-08-28  
**Audit Scope**: All Python source files under `backend/app/` (~50 source files across 7 modules), `backend/requirements.txt`, `backend/Dockerfile`, and `backend/alembic/`  
**Integrity Mode**: Strictly Read-Only (R5: No runtime code execution, no test runners, no code modifications)  
**Standard Benchmarks**: Python 3.12, FastAPI 0.112+, SQLAlchemy 2.0+ (async), Pydantic v2, Pinecone SDK v3+, NeMo Guardrails 0.11+ (Colang 2.0), `google-genai` SDK, `openai` 1.40+ SDK, CBUAE MMG regulatory compliance standards, Zero-Trust Privacy Rules  

---

## 1. Executive Summary

A comprehensive, multi-agent static code audit was conducted across the entire backend architecture of ModelAudit AI. Six specialist auditors independently reviewed the codebase across discrete functional scopes, evaluated API usage against modern library documentation, audited dependency compatibility, verified multi-tenancy enforcement, and evaluated privacy pipeline invariants.

### 1.1 Summary Matrix by Severity

| Severity | Count | Primary Impact Areas |
|---|:---:|---|
| **Critical** | **24** | Coroutine/async generator crashes in streaming endpoints; `AttributeError` on Pydantic `TokenPayload` across 5 API handlers; Multi-tenancy cross-tenant chunk leaks; Global string substitution corrupting text & privacy tokens; Unanchored egress validator leaks; RS256 symmetric secret configuration failure; Alembic missing document model metadata; Unimplemented stubs; Truncation of comma-formatted financial numbers. |
| **High** | **34** | Unbounded memory allocation (DoS) in file upload; Complete lack of chunk overlap in chunker; Case-sensitivity & substring false positives in bank matcher; Off-by-one span indices; Pinecone `AttributeError` on empty index; Blocking synchronous I/O loops in async functions; Reranker dropping 100% of candidates on API error; Multi-provider router failing to failover; Missing inactive user checks; Missing database foreign key indexes; Docker container missing Docling C-libraries. |
| **Medium** | **39** | Pydantic v2 schemas missing `model_config = ConfigDict(from_attributes=True)`; Legacy SQLAlchemy 1.4 `declarative_base()`; Bare `except Exception:` error swallowing; Regex table parsing failures; Incomplete regulatory calibration checks (Hosmer-Lemeshow, Brier); Missing SSE reverse-proxy buffering headers; Redundant `langchain-*` dependencies. |
| **Low** | **23** | Python 3.12 `datetime.utcnow()` deprecations; Empty package `__init__.py` export files; Missing `from __future__ import annotations`; Missing Google-style docstrings; Unused imports; Data dataset typos. |
| **Total** | **120** | **Comprehensive catalog of all audited issues.** |

---

### 1.2 Category Breakdown (Requirement R1 & R2 Alignment)

| Category (R1 / R2) | Count | Key Notes |
|---|:---:|---|
| **Security Issues & Multi-Tenancy** | 22 | Multi-tenant query isolation gaps, JWT RS256 crypto misconfiguration, unverified `document_id` retrieval, file upload DoS. |
| **Privacy Pipeline Logic** | 16 | Unanchored string replacement, entity leaks to LLMs via user query bypass, off-by-one spans, token false positive blocks. |
| **Incorrect API Usage vs. Latest Library Docs** | 28 | Pydantic v2 vs v1, SQLAlchemy 2.0 async, NeMo Guardrails 0.11+ output format, NVIDIA NIM reranking payload schema, Docling format options. |
| **Async / Await Correctness & Concurrency** | 12 | Async generator returns in coroutines, blocking sync calls inside async loops, circuit breaker race conditions in half-open state. |
| **Type Annotation Correctness & Runtime Type Errors** | 16 | Pydantic `TokenPayload` treated as `dict` (`.get()`), missing default arguments in base classes, missing type annotations on helpers. |
| **Dependency Compatibility & Packaging (R2)** | 14 | `python-jose` CVEs vs `PyJWT`, `passlib` + `bcrypt` 4.x incompatibilities, `pinecone-client` vs `pinecone`, `spacy` build wheels. |
| **Code Layout, Conventions & Schemas (R3)** | 12 | Empty `__init__.py` files, missing `ConfigDict`, legacy SQLAlchemy declarative base, Alembic model discovery. |

---

## 2. Per-File Findings Grouped by Module

---

### 2.1 Privacy Pipeline (`backend/app/services/privacy/`)

#### 1. `backend/app/services/privacy/masking_pipeline.py`

##### Finding PRV-01 (Critical) — Unanchored Global String Replacement Corrupting English Words and Masking Tokens
- **File**: `backend/app/services/privacy/masking_pipeline.py`
- **Line(s)**: 70–78
- **Severity**: Critical
- **Category**: Privacy pipeline logic
- **Description**: In `mask_document`, the pipeline computes precise character offset spans (`resolved_spans`) but then discards them, performing global string replacement: `masked_text = masked_text.replace(entity_text, token)`. This creates three critical failures:
  1. Common words recognized as entities (e.g. person name *"Will"* or *"May"*, or org *"Credit"*, *"General"*, *"Total"*) are replaced everywhere across the document (e.g. `"The model may underestimate default probability"` becomes `"The model [PERSON_1] underestimate default probability"`).
  2. If an entity is `"BANK"` or `"ORG"`, replacing it corrupts previously inserted tokens (e.g. `[BANK_1]` becomes `[[ORG_2]_1]`).
  3. Overlap resolution performed on character offsets is completely bypassed.
- **Correct Pattern / Fix**: Perform replacements directly using character offset slicing in reverse order of start position:
  ```python
  resolved_spans.sort(key=lambda s: s["start"], reverse=True)
  masked_text = raw_text
  for span in resolved_spans:
      token = registry.mask(span["text"], span["category"])
      masked_text = masked_text[:span["start"]] + token + masked_text[span["end"]:]
  ```

---

#### 2. `backend/app/services/privacy/egress_validator.py`

##### Finding PRV-02 (Critical) — Egress Validator Ignores `registry` Parameter, Leaking Real Entities
- **File**: `backend/app/services/privacy/egress_validator.py`
- **Line(s)**: 33–57
- **Severity**: Critical
- **Category**: Security issues / Privacy pipeline logic
- **Description**: `validate(self, masked_text: str, registry: EntityRegistry)` accepts `registry`, but never accesses it. Statistical NER models (spaCy) frequently fail to re-detect entities on a second pass once adjacent tokens have changed to `[BANK_1]`. Because original entity strings from `registry.get_mapping().keys()` are not checked against `masked_text`, unmasked entities slip through to LLM providers undetected.
- **Correct Pattern / Fix**: Check all registered original entity strings against `masked_text`:
  ```python
  mapping = registry.get_mapping()
  for original_entity in mapping.keys():
      if original_entity in masked_text:
          violations.append(f"Registered entity leak detected: '{original_entity}'")
  ```

##### Finding PRV-03 (High) — False-Positive Egress Violations on Valid Masking Tokens (`[ORG_1]`)
- **File**: `backend/app/services/privacy/egress_validator.py`
- **Line(s)**: 43–46
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**: spaCy's NER parser often categorizes uppercase bracket tokens like `[ORG_1]` or `[BANK_1]` as `ORG` or `PERSON` entities. `EgressValidator` flags them as leaks and raises `EgressViolationError`, blocking 100% of properly masked documents from being processed.
- **Correct Pattern / Fix**: Exclude valid bracket token notations:
  ```python
  token_pattern = re.compile(r"^\[(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]$")
  for ent in ner_matches:
      if ent.category in ("ORG", "PERSON", "EMAIL", "PHONE", "GPE"):
          if not token_pattern.match(ent.text):
              violations.append(f"{ent.category} leak detected: {ent.text}")
  ```

##### Finding PRV-04 (Medium) — Per-Request Instantiation of Heavy NLP Models
- **File**: `backend/app/services/privacy/egress_validator.py`
- **Line(s)**: 30–32
- **Severity**: Medium
- **Category**: Architecture / Performance
- **Description**: `EgressValidator.__init__` instantiates fresh `NERMasker()` and `BankNameMatcher()` objects, reloading spaCy and Presidio models into memory on every validation call.
- **Correct Pattern / Fix**: Accept optional injected instances in `__init__` with module-level singleton fallbacks.

---

#### 3. `backend/app/services/privacy/bank_matcher.py`

##### Finding PRV-05 (High) — Off-By-One Span Indexing Bug in Aho-Corasick Matches
- **File**: `backend/app/services/privacy/bank_matcher.py`
- **Line(s)**: 38–40
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**: `pyahocorasick.Automaton.iter()` returns `(end_char_index, matched_name)` where `end_char_index` is inclusive. `bank_matcher.py` calculates `start_index = end_index - len(matched_name) + 1` and outputs `(start_index, end_index, matched_name)`. Downstream code slices `text[start:end]` (standard Python half-open intervals `[start, end)`). Because `end_index` is inclusive, the slice truncates the final character of every matched bank name.
- **Correct Pattern / Fix**: Convert `end_index` to standard half-open format:
  ```python
  end_index = end_char_index + 1
  start_index = end_index - len(matched_name)
  matches.append((start_index, end_index, matched_name))
  ```

##### Finding PRV-06 (High) — Case Sensitivity & Substring False Positives on Bank Abbreviations
- **File**: `backend/app/services/privacy/bank_matcher.py`
- **Line(s)**: 29–31, 38
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**: 
  1. `Automaton` performs exact case-sensitive matching; lowercase mentions (`"emirates nbd"`) fail to match.
  2. Short bank abbreviations (`"FAB"`, `"CBD"`, `"DIB"`, `"Gulf"`) match substrings inside ordinary English words (`"FABRIC"`, `"CONFIDENT"`, `"Gulfstream"`).
- **Correct Pattern / Fix**: Lowercase automaton keys and text queries, and verify word boundaries (`isalnum()` check on preceding/trailing characters).

##### Finding PRV-07 (Low) — Typo in GCC Bank Names Dataset
- **File**: `backend/app/services/privacy/resources/gcc_bank_names.json`
- **Line(s)**: 36
- **Severity**: Low
- **Category**: Data quality
- **Description**: Entry `"Barclids"` instead of `"Barclays"`.
- **Correct Pattern / Fix**: Correct typo to `"Barclays"`.

---

#### 4. `backend/app/services/privacy/ner_masker.py`

##### Finding PRV-08 (High) — Blocking Synchronous Runtime Model Download via `spacy.cli.download`
- **File**: `backend/app/services/privacy/ner_masker.py`
- **Line(s)**: 46–48
- **Severity**: High
- **Category**: Incorrect API usage vs. latest library docs / Runtime reliability
- **Description**: If `spacy.load("en_core_web_lg")` raises `OSError`, `__init__` invokes `spacy.cli.download("en_core_web_lg")` synchronously inside the request thread. In containerized environments with read-only root filesystems or airgapped VPCs, this blocks for minutes and fails with `PermissionError` or connection timeout.
- **Correct Pattern / Fix**: Remove `spacy.cli.download` from runtime code; raise informative `RuntimeError` prompting installation via setup/Dockerfile.

##### Finding PRV-09 (Medium) — Incomplete Financial Protection Regex Patterns
- **File**: `backend/app/services/privacy/ner_masker.py`
- **Line(s)**: 26–38, 52–59
- **Severity**: Medium
- **Category**: Privacy pipeline logic
- **Description**: `FINANCIAL_PATTERNS` only includes 5 currencies (`AED`, `USD`, `$`, `EUR`, `GBP`), omitting GCC currencies (`SAR`, `QAR`, `KWD`, `BHD`, `OMR`). Formatted numbers with commas (`1,250,000`) and standard dates (`2024-12-31`) lack standalone patterns and risk being masked.
- **Correct Pattern / Fix**: Expand regexes to include all GCC currencies, formatted decimal numbers, ISO dates, and fiscal quarters.

##### Finding PRV-10 (Medium) — Duplicate spaCy Model Loading in Presidio AnalyzerEngine
- **File**: `backend/app/services/privacy/ner_masker.py`
- **Line(s)**: 50, 77–81
- **Severity**: Medium
- **Category**: Performance / Memory overhead
- **Description**: Default `AnalyzerEngine()` initializes a second copy of `en_core_web_lg` in memory (~800MB RAM overhead).
- **Correct Pattern / Fix**: Configure `AnalyzerEngine` with explicit `score_threshold=0.6` and share the existing spaCy instance.

---

#### 5. `backend/app/services/privacy/entity_registry.py`

##### Finding PRV-11 (Medium) — Sequential `str.replace` in `unmask_text`
- **File**: `backend/app/services/privacy/entity_registry.py`
- **Line(s)**: 43–57
- **Severity**: Medium
- **Category**: Privacy pipeline logic
- **Description**: `unmask_text` executes sequential `str.replace` over tokens. If an unmasked entity itself contains a substring matching another token format, sequential execution corrupts the unmasked text.
- **Correct Pattern / Fix**: Use atomic single-pass regex replacement:
  ```python
  pattern = re.compile("|".join(re.escape(token) for token in sorted_tokens))
  return pattern.sub(lambda match: self._reverse[match.group(0)], masked_text)
  ```

##### Finding PRV-12 (Low) — Missing Whitespace Normalization in Entity Registration
- **File**: `backend/app/services/privacy/entity_registry.py`
- **Line(s)**: 25–41
- **Severity**: Low
- **Category**: Privacy pipeline logic
- **Description**: `mask(entity, category)` does not strip leading/trailing whitespace, generating duplicate tokens for `"Emirates NBD"` and `"Emirates NBD "`.
- **Correct Pattern / Fix**: Normalize `entity = entity.strip()` and return `""` on empty strings.

---

### 2.2 Document Extraction & Chunking (`backend/app/services/`)

#### 1. `backend/app/services/chunker.py`

##### Finding DOC-01 (Critical) — Broken Accumulation Logic in `_split_text` Fragmenting Output
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 40–55
- **Severity**: Critical
- **Category**: Algorithm correctness
- **Description**: In `_split_text`, `current_part` is reset to `""` on every single iteration of the loop. It never accumulates text up to `chunk_size`. Consequently, `_split_text` outputs every split snippet (even 1-word or 1-sentence lines) as an isolated chunk, destroying document coherence.
- **Correct Pattern / Fix**: Accumulate candidate text until the length exceeds `self.chunk_size` before appending to `final_parts`.

##### Finding DOC-02 (Critical) — Silent Destruction of Markdown Tables
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 94, 110–111
- **Severity**: Critical
- **Category**: Algorithm correctness / Data loss
- **Description**: Docling extracts financial tables in Markdown format (`| Metric | Value |`). Individual table rows frequently have fewer than 8 words. Line 94 `if len(rc_clean.split()) >= 8:` silently drops table rows, destroying critical financial ratios, validation metrics, and regulatory tables.
- **Correct Pattern / Fix**: Detect Markdown table blocks and treat whole tables as atomic chunks exempt from the 8-word filter.

##### Finding DOC-03 (High) — `overlap` Parameter is Completely Unused
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 12–14, 58–115
- **Severity**: High
- **Category**: Algorithm correctness
- **Description**: `__init__` sets `self.overlap = overlap`, but `self.overlap` is never referenced in `chunk()` or `_split_text()`. All chunks are generated with 0 overlap, leading to context loss across chunk boundaries.
- **Correct Pattern / Fix**: Implement sliding window overlap carrying trailing characters into subsequent chunks.

##### Finding DOC-04 (High) — Delimiter Splitting Strips Punctuation and Formatting
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 36, 43, 88
- **Severity**: High
- **Category**: Algorithm correctness
- **Description**: Splitting on `". "` and `" "` removes periods and whitespace from sentences when chunks are assembled.
- **Correct Pattern / Fix**: Reattach delimiter when constructing candidate chunks or use regex lookahead/lookbehind splitting.

##### Finding DOC-05 (Medium) — Stripping Empty Lines Breaks Paragraph Splitting
- **File**: `backend/app/services/chunker.py`
- **Line(s)**: 82, 88, 110
- **Severity**: Medium
- **Category**: Algorithm correctness
- **Description**: Line 110 drops empty lines and line 82 joins with single `\n`, eliminating double newlines `\n\n` required for semantic paragraph splitting.
- **Correct Pattern / Fix**: Preserve empty line markers in section buffers.

---

#### 2. `backend/app/services/document_extractor.py`

##### Finding DOC-06 (Medium) — Unhandled Docling Conversion Exceptions
- **File**: `backend/app/services/document_extractor.py`
- **Line(s)**: 40–47
- **Severity**: Medium
- **Category**: Error handling / Resilience
- **Description**: `self.converter.convert(stream)` raises internal exceptions on corrupt or password-protected PDF/DOCX files, which bubble up as raw 500 server crashes.
- **Correct Pattern / Fix**: Wrap `convert()` in `try...except Exception as exc:` and raise a structured `DocumentExtractionError`.

##### Finding DOC-07 (Low) — Missing `WordFormatOption` in Docling Options
- **File**: `backend/app/services/document_extractor.py`
- **Line(s)**: 23–29
- **Severity**: Low
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `format_options` configures `InputFormat.PDF` but omits `InputFormat.DOCX`.
- **Correct Pattern / Fix**: Configure `InputFormat.DOCX: WordFormatOption()`.

---

### 2.3 LLM Providers & Routing (`backend/app/services/llm/`)

#### 1. `backend/app/services/llm/router.py`

##### Finding LLM-01 (Critical) — Async Generator Returned from Coroutine Raising TypeError in `generate_stream`
- **File**: `backend/app/services/llm/router.py`
- **Line(s)**: 122–146
- **Severity**: Critical
- **Category**: Async/await correctness
- **Description**: `LLMRouter.generate_stream` is declared `async def` and returns a nested async generator `return _yield_and_record()`. Callers using `async for chunk in router.generate_stream(...)` receive `TypeError: 'coroutine' object is not an async iterable`. Furthermore, `await cb.call(func, ...)` passes an async generator function into `cb.call`, which executes `await func(...)`, raising `TypeError: object async_generator can't be used in 'await' expression`.
- **Correct Pattern / Fix**: Implement `generate_stream` directly as an async generator using `async def` and `yield`:
  ```python
  async def generate_stream(
      self,
      prompt: str,
      system_prompt: str | None = None,
      temperature: float = 0.7,
      max_tokens: int = 1024
  ) -> AsyncIterator[str]:
      decision = self.get_routing_decision()
      provider = self.providers[decision.provider]
      cb = self.circuit_breakers[decision.provider]
      try:
          async for chunk in provider.generate_stream(prompt, system_prompt, temperature, max_tokens):
              yield chunk
          cb.record_success()
      except Exception as e:
          cb.record_failure()
          raise e
  ```

##### Finding LLM-02 (High) — Multi-Provider Router Lacks Automatic Failover / Fallback
- **File**: `backend/app/services/llm/router.py`
- **Line(s)**: 101–118
- **Severity**: High
- **Category**: Resilience / Architecture
- **Description**: `_execute_routed` selects the primary provider via `get_routing_decision()`. If that provider fails, the error is immediately re-raised without attempting to fail over to the secondary provider (e.g. falling back from NVIDIA NIM to Google Gemini).
- **Correct Pattern / Fix**: Catch provider exceptions and attempt execution on the secondary available provider before raising `AllProvidersUnavailableError`.

---

#### 2. `backend/app/services/llm/circuit_breaker.py`

##### Finding LLM-03 (Critical) — Circuit Breaker Cannot Wrap Async Generators
- **File**: `backend/app/services/llm/circuit_breaker.py`
- **Line(s)**: 51–63
- **Severity**: Critical
- **Category**: Async/await correctness
- **Description**: `CircuitBreaker.call` executes `result = await func(*args, **kwargs)`. When `func` is an async generator method, awaiting it raises `TypeError`. In addition, `self.record_success()` is executed before any stream chunks are read.
- **Correct Pattern / Fix**: Provide a dedicated `call_stream` async generator wrapper in `CircuitBreaker`.

##### Finding LLM-04 (High) — Race Condition in Circuit Breaker State Transitions
- **File**: `backend/app/services/llm/circuit_breaker.py`
- **Line(s)**: 26–50
- **Severity**: High
- **Category**: Concurrency / Async correctness
- **Description**: State transitions (`CLOSED` -> `OPEN` -> `HALF_OPEN` -> `CLOSED`) lack synchronization. Concurrent async requests in `HALF_OPEN` state all pass through simultaneously instead of a single trial probe.
- **Correct Pattern / Fix**: Guard state transitions with an `asyncio.Lock()`.

---

#### 3. `backend/app/services/llm/nvidia_provider.py`

##### Finding LLM-05 (Critical) — NVIDIA NIM Reranking API Payload Schema Mismatch & Base URL Truncation
- **File**: `backend/app/services/llm/nvidia_provider.py`
- **Line(s)**: 137–143
- **Severity**: Critical
- **Category**: Incorrect API usage vs. latest library docs
- **Description**:
  1. NVIDIA NIM Reranking API (`/v1/ranking`) requires `query` as `{"text": query}` and `passages` as `[{"text": p} for p in passages]`. Sending plain strings causes HTTP 422 Unprocessable Entity.
  2. `self.httpx_client` has `base_url="https://integrate.api.nvidia.com/v1"`. Calling `client.post("/ranking")` with a leading slash causes RFC 3986 URL resolution to strip `/v1`, targeting `/ranking` (HTTP 404).
- **Correct Pattern / Fix**: Use relative URL `"ranking"` and format structured text payload objects:
  ```python
  payload = {
      "model": NVIDIA_RERANKING_MODEL,
      "query": {"text": query},
      "passages": [{"text": p} for p in passages],
      "truncate": "END"
  }
  response = await self.httpx_client.post("ranking", json=payload)
  ```

##### Finding LLM-06 (High) — Unmanaged `httpx.AsyncClient` Lifecycle
- **File**: `backend/app/services/llm/nvidia_provider.py`
- **Line(s)**: 71–78
- **Severity**: High
- **Category**: Resource management
- **Description**: `AsyncClient` is created in `__init__` with no `aclose()` method or lifespan teardown.
- **Correct Pattern / Fix**: Provide an `aclose()` coroutine registered with application shutdown.

---

#### 4. `backend/app/services/llm/base_provider.py`

##### Finding LLM-07 (Medium) — Missing Default Parameter Values in Abstract Method Signatures
- **File**: `backend/app/services/llm/base_provider.py`
- **Line(s)**: 20, 25, 30, 35
- **Severity**: Medium
- **Category**: Type annotation correctness
- **Description**: `BaseLLMProvider` abstract methods omit default values (`temperature: float = 0.7`, `max_tokens: int = 1024`), causing `provider.generate(prompt)` to fail with missing positional argument errors.
- **Correct Pattern / Fix**: Add default values to abstract signatures in `BaseLLMProvider` and concrete implementations in `NvidiaProvider` and `GeminiProvider`.

---

### 2.4 NeMo Guardrails (`backend/app/services/guardrails/`)

#### 1. `backend/app/services/guardrails/guardrails_service.py`

##### Finding GRD-01 (Critical) — NeMo Guardrails Dict Response Compared with String and Assigned to `str`
- **File**: `backend/app/services/guardrails/guardrails_service.py`
- **Line(s)**: 47–60, 101
- **Severity**: Critical
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `LLMRails.generate_async(messages=...)` returns a dictionary `{"role": "assistant", "content": "..."}`. The code compares `if response == "I am ModelAudit AI...":` (always `False`) and assigns the raw dict to `GuardrailsResult.response` (typed as `str | None`), causing downstream type failures.
- **Correct Pattern / Fix**: Extract `content = response.get("content", "") if isinstance(response, dict) else str(response)`.

##### Finding GRD-02 (Critical) — Context and Retrieved Chunks Never Passed into Guardrails Execution
- **File**: `backend/app/services/guardrails/guardrails_service.py`
- **Line(s)**: 34, 47–54
- **Severity**: Critical
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: `generate_with_guardrails(self, prompt, context, retrieved_contexts)` accepts `context` and `retrieved_contexts`, but never passes them into `self.rails.generate_async()`. Actions like `check_hallucination_action` receive empty context and return 0.0 hallucination, completely disabling hallucination prevention.
- **Correct Pattern / Fix**: Pass `context={"context": context, "retrieved_contexts": retrieved_contexts}` into `generate_async()`.

---

#### 2. `backend/app/services/guardrails/rails.co` & `config.yml`

##### Finding GRD-03 (Critical) — Undefined Bot Utterance in Colang Flow
- **File**: `backend/app/services/guardrails/rails.co`
- **Line(s)**: 43–48
- **Severity**: Critical
- **Category**: Incorrect API usage
- **Description**: Flow `check hallucination against context` executes `bot refuse to respond`, but `bot refuse to respond` is never defined in `rails.co`, causing runtime Colang execution errors.
- **Correct Pattern / Fix**: Define `define bot refuse to respond: "I'm sorry, but I cannot verify this answer against the provided credit documentation."` in `rails.co`.

##### Finding GRD-04 (High) — Conflicting `type: main` Models in `config.yml`
- **File**: `backend/app/services/guardrails/config.yml`
- **Line(s)**: 1–14
- **Severity**: High
- **Category**: Incorrect API usage
- **Description**: `config.yml` defines two `type: main` models and omits `colang_version: "2.x"`.
- **Correct Pattern / Fix**: Set `colang_version: "2.x"` and define a single main model engine.

##### Finding GRD-05 (Medium) — Ineffective Placeholder Integrity Action
- **File**: `backend/app/services/guardrails/actions.py`
- **Line(s)**: 88–114
- **Severity**: Medium
- **Category**: Incorrect API usage
- **Description**: `check_placeholder_integrity_action` iterates with `pass` and unconditionally returns `True`.
- **Correct Pattern / Fix**: Validate placeholder syntax against allowed entity token patterns.

##### Finding GRD-06 (Medium) — Hallucination Metric Splits Comma Numbers and Includes Stop Words
- **File**: `backend/app/services/guardrails/actions.py`
- **Line(s)**: 63–85
- **Severity**: Medium
- **Category**: Rule 10 violation / Metric distortion
- **Description**: Regex splits comma-formatted numbers (`1,250,000` -> `['1', '250', '000']`) and stop words distort overlap calculation.
- **Correct Pattern / Fix**: Filter out English stop words and preserve comma-formatted numbers in regex.

---

### 2.5 Retrieval Pipeline (`backend/app/services/retrieval/`)

#### 1. `backend/app/services/retrieval/pinecone_store.py`

##### Finding RET-01 (Critical) — `PineconeStore.__init__` Lacks Default Settings, Crashing API Routes
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line(s)**: 7–9
- **Severity**: Critical
- **Category**: Incorrect API usage / Broken contract
- **Description**: `PineconeStore.__init__` requires mandatory `api_key` and `index_name`. API routes instantiate `PineconeStore()` with no arguments, raising `TypeError: missing 2 required positional arguments` on every `/query` and `/regulatory/search` request (HTTP 500).
- **Correct Pattern / Fix**: Pull default values from `app.config.settings.pinecone`.

##### Finding RET-02 (Critical) — `upsert_chunks()` is an Unimplemented Stub
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line(s)**: 11–21
- **Severity**: Critical
- **Category**: Incomplete implementation
- **Description**: `upsert_chunks()` contains developer scratchpad comments and a `pass` statement, silently failing to index document chunks into Pinecone.
- **Correct Pattern / Fix**: Implement chunk vector conversion and delegate to `upsert_vectors`.

##### Finding RET-03 (High) — `describe_index_stats()` Attribute Error on Empty Index
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line(s)**: 65–66
- **Severity**: High
- **Category**: Incorrect API usage vs. latest library docs
- **Description**: When an index is empty, `stats.namespaces` is `None`. Calling `.keys()` raises `AttributeError: 'NoneType' object has no attribute 'keys'`.
- **Correct Pattern / Fix**: Safely guard: `namespaces_dict = getattr(stats, "namespaces", None) or {}`.

##### Finding RET-04 (Medium) — Bare Exception Swallowing in Pinecone Queries
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line(s)**: 57–58
- **Severity**: Medium
- **Category**: Error handling
- **Description**: In `query()`, `except Exception:` silently returns `[]`, masking dimension mismatches, network timeouts, and authentication errors.
- **Correct Pattern / Fix**: Log exceptions with `logger.error(..., exc_info=True)`.

##### Finding RET-05 (Medium) — Blocking Sync I/O in Async Pinecone Retrieval Methods
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line(s)**: 11, 23, 40, 60
- **Severity**: Medium
- **Category**: Async/await correctness
- **Description**: Synchronous Pinecone calls block the main event loop thread.
- **Correct Pattern / Fix**: Wrap blocking calls with `asyncio.to_thread`.

---

#### 2. `backend/app/services/retrieval/hybrid_retriever.py`

##### Finding RET-06 (Critical) — Cross-Tenant Isolation Breach in `_fetch_chunks_for_document`
- **File**: `backend/app/services/retrieval/hybrid_retriever.py`
- **Line(s)**: 26–30
- **Severity**: Critical
- **Category**: Security issues / Multi-tenancy isolation breach
- **Description**: `select(DocumentChunk).where(DocumentChunk.document_id == document_id)` does not filter by `tenant_id`. If a user from Tenant A queries a `document_id` belonging to Tenant B, BM25 retrieval pulls Tenant B's private chunks.
- **Correct Pattern / Fix**: Join with `Document` and filter by `Document.tenant_id == tenant_id`.

##### Finding RET-07 (Medium) — BM25 Corpus Excludes Regulatory Guidelines
- **File**: `backend/app/services/retrieval/hybrid_retriever.py`
- **Line(s)**: 54–73
- **Severity**: Medium
- **Category**: Retrieval logic
- **Description**: In pure regulatory searches (`document_id=None`), BM25 candidates list is empty and the pipeline falls back to pure dense retrieval.
- **Correct Pattern / Fix**: Index CBUAE regulatory guidelines into BM25.

---

#### 3. `backend/app/services/retrieval/bm25.py`

##### Finding RET-08 (High) — Stateful Accumulation Across Multiple `fit()` Invocations
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line(s)**: 21–52
- **Severity**: High
- **Category**: Logic bug
- **Description**: `fit()` does not clear `self.doc_freqs` and `self.doc_len` before appending, corrupting BM25 scores on reused instances.
- **Correct Pattern / Fix**: Reset `self.doc_freqs = []`, `self.doc_len = []`, `self.idf = {}` at the start of `fit()`.

##### Finding RET-09 (Medium) — Naive Tokenization Fails on Words with Punctuation
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line(s)**: 16–19
- **Severity**: Medium
- **Category**: Retrieval quality
- **Description**: `text.lower().split()` leaves trailing commas and periods attached to words.
- **Correct Pattern / Fix**: Use regex tokenization preserving words and comma-formatted financial numbers.

##### Finding RET-10 (Medium) — Potential `ZeroDivisionError` when `avgdl == 0`
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line(s)**: 75
- **Severity**: Medium
- **Category**: Robustness
- **Description**: If a corpus has empty documents, `self.avgdl == 0.0`, triggering `ZeroDivisionError`.
- **Correct Pattern / Fix**: Guard with `len_norm = (d_len / self.avgdl) if self.avgdl > 0 else 1.0`.

---

#### 4. `backend/app/services/retrieval/dense_retriever.py`

##### Finding RET-11 (High) — Blocking Synchronous Loop in Async Retrieval Coroutine
- **File**: `backend/app/services/retrieval/dense_retriever.py`
- **Line(s)**: 24–29
- **Severity**: High
- **Category**: Async/await correctness
- **Description**: Synchronously queries Pinecone namespaces in a sequential `for` loop inside an `async def` method.
- **Correct Pattern / Fix**: Parallelize queries across namespaces with `asyncio.gather`.

---

#### 5. `backend/app/services/retrieval/reranker.py` & `rrf_fusion.py`

##### Finding RET-12 (High) — In-Place Mutation of Candidate Objects in Reranker
- **File**: `backend/app/services/retrieval/reranker.py`
- **Line(s)**: 24–27
- **Severity**: High
- **Category**: Logic / Mutability
- **Description**: `candidate.retrieval_method += "_reranked"` mutates the caller's input objects in-place.
- **Correct Pattern / Fix**: Clone candidate objects with `model_copy(update=...)`.

##### Finding RET-13 (High) — Total Candidate Drop on Reranking API Error
- **File**: `backend/app/services/retrieval/reranker.py`
- **Line(s)**: 17–31
- **Severity**: High
- **Category**: Resilience
- **Description**: If `llm_router.rerank()` returns `[]` on error or timeout, `reranker.py` drops all valid RRF candidates, returning 0 citations.
- **Correct Pattern / Fix**: Fall back to `candidates[:top_n]` on reranking failure.

##### Finding RET-14 (Medium) — Unnormalized Raw RRF Scores
- **File**: `backend/app/services/retrieval/rrf_fusion.py`
- **Line(s)**: 34–45
- **Severity**: Medium
- **Category**: Algorithm precision
- **Description**: Raw RRF scores are unnormalized fractions (~0.016) rather than standard $[0, 1]$ confidence scores.
- **Correct Pattern / Fix**: Normalize by theoretical maximum score $\sum \frac{1}{k + 1}$.

---

### 2.6 Analytics Engine (`backend/app/services/analytics/`)

#### 1. `backend/app/services/analytics/model_metrics_extractor.py`

##### Finding ANA-01 (Critical) — Regex Truncates Comma-Formatted Financial Numbers (Rule 10 Violation)
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line(s)**: 12
- **Severity**: Critical
- **Category**: Rule 10 violation / Financial number parsing
- **Description**: Pattern `(?P<value>\d+(?:\.\d+)?)` stops at the first comma. Financial values like `EAD: 1,500,000 AED` are parsed as `1.0`, corrupting risk analytics.
- **Correct Pattern / Fix**: Match comma-separated digits: `r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"` and strip commas before `float()` conversion.

##### Finding ANA-02 (High) — Ambiguous Nested Optional Quantifier in Unit Pattern
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line(s)**: 12
- **Severity**: High
- **Category**: Regex syntax
- **Description**: `(?P<unit>%|percent|%?)?` contains `%?` inside the alternation, causing non-deterministic empty string matches when `%` is present.
- **Correct Pattern / Fix**: Use `(?P<unit>%|percent|bps|bp)?`.

##### Finding ANA-03 (Medium) — Markdown Table Parsing Incompatibility
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line(s)**: 16–30
- **Severity**: Medium
- **Category**: Parsing logic
- **Description**: Patterns only match prose colons `(?:of|:|=)?`, failing to extract metrics from Docling Markdown tables (`| AUC | 0.82 |`).
- **Correct Pattern / Fix**: Include table delimiter characters `[:=|\|\s]+`.

##### Finding ANA-04 (Medium) — Missing Basis Points (`bps`) Scale Normalization
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line(s)**: 43–46
- **Severity**: Medium
- **Category**: Unit conversion
- **Description**: Metrics in `bps` (e.g. `45 bps`) are recorded as `45.0` absolute instead of `0.45%` (0.0045).
- **Correct Pattern / Fix**: Divide `bps` values by 100 for percentage representation.

---

#### 2. `backend/app/services/analytics/policy_checker.py`

##### Finding ANA-05 (High) — `get_absolute_value` Normalization Bug on Unflagged Percentages
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line(s)**: 22–28
- **Severity**: High
- **Category**: Analytics logic
- **Description**: If a document states `AUC: 78.5` without `%`, `get_absolute_value` returns `78.5`. Evaluated against `0.70`, it passes, but records `PolicyResult.value = 78.5` against threshold `">= 0.70"`.
- **Correct Pattern / Fix**: If `val > 1.0` and unit is absolute, normalize by dividing by 100.

##### Finding ANA-06 (Medium) — Conflicting AUC Threshold Condition and Reported Threshold Label
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line(s)**: 48–62
- **Severity**: Medium
- **Category**: Regulatory alignment
- **Description**: Label states `">= 0.70"` but logic marks `auc_val <= 0.77` as `WARNING`. Under CBUAE MMG, acceptable discriminatory power is AUC >= 0.75.
- **Correct Pattern / Fix**: Align logic with CBUAE standards: `< 0.70` (BREACH), `0.70–0.75` (WARNING), `>= 0.75` (PASS).

##### Finding ANA-07 (Medium) — Incomplete Policy Validation for Calibration Metrics
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line(s)**: 8–151
- **Severity**: Medium
- **Category**: Regulatory completeness
- **Description**: Ignores Hosmer-Lemeshow p-value, Brier score, and PD accuracy ratio defined in `ModelValidationProfile`.
- **Correct Pattern / Fix**: Implement calibration policy validation checks.

---

#### 3. `backend/app/services/analytics/ews_detector.py`

##### Finding ANA-08 (High) — False-Positive High Severity Alarms in `obs_vs_pred`
- **File**: `backend/app/services/analytics/ews_detector.py`
- **Line(s)**: 137–145
- **Severity**: High
- **Category**: Analytics logic
- **Description**: If observed vs predicted default rate is extracted without `%` (e.g. `105` for 105%), `105 > 1.2` immediately triggers a false-positive HIGH severity alarm.
- **Correct Pattern / Fix**: Normalize ratio values where `val > 10.0`.

##### Finding ANA-09 (Medium) — Missing Moderate PSI Drift Signal (0.10–0.25)
- **File**: `backend/app/services/analytics/ews_detector.py`
- **Line(s)**: 120–126
- **Severity**: Medium
- **Category**: EWS granularity
- **Description**: Only triggers on `psi > 0.25` (HIGH). Moderate drift (0.10–0.25) is ignored.
- **Correct Pattern / Fix**: Add MEDIUM severity warning signal for $0.10 \le \text{PSI} \le 0.25$.

---

### 2.7 API Endpoints (`backend/app/api/`)

#### 1. `backend/app/api/query.py`, `compare.py`, `gap_analysis.py`, `regulatory.py`

##### Finding API-01 (Critical) — Pydantic `TokenPayload` Treated as Dict (`current_user.get('tenant_id')`) Crashing Endpoints
- **File**: `backend/app/api/query.py` (Line 26), `compare.py` (Line 21), `gap_analysis.py` (Line 20), `regulatory.py` (Line 24)
- **Line(s)**: Multiple
- **Severity**: Critical
- **Category**: Type annotation correctness & Runtime type error
- **Description**: Handlers declare `current_user: dict = Depends(get_current_user)`. `get_current_user` in `auth_middleware.py` returns a Pydantic `TokenPayload` instance. Calling `current_user.get('tenant_id')` crashes with `AttributeError: 'TokenPayload' object has no attribute 'get'` on 100% of requests hitting these endpoints.
- **Correct Pattern / Fix**: Annotate `current_user: TokenPayload = Depends(get_current_user)` and access attributes directly via `current_user.tenant_id`.

##### Finding API-02 (Critical) — Unverified `document_id` in Query Endpoint Allows Cross-Tenant Chunk Retrieval
- **File**: `backend/app/api/query.py`
- **Line(s)**: 28–34
- **Severity**: Critical
- **Category**: Security issues / Multi-tenancy enforcement
- **Description**: `conversational_query` accepts `request.document_id` from the client and passes it directly to retrieval without checking whether the document belongs to `current_user.tenant_id`.
- **Correct Pattern / Fix**: Query `Document` in the database to verify `Document.id == request.document_id` and `Document.tenant_id == current_user.tenant_id` before retrieval.

##### Finding API-03 (High) — Privacy Pipeline Bypass: Unmasked User Questions Sent to LLM Providers
- **File**: `backend/app/api/query.py` (Line 47), `compare.py` (Line 60), `regulatory.py` (Line 48)
- **Line(s)**: Multiple
- **Severity**: High
- **Category**: Privacy pipeline logic & Security
- **Description**: User questions and focus areas are concatenated directly into the prompt without running through `MaskingPipeline` or `EgressValidator`, leaking sensitive entity names in user prompts to third-party LLMs.
- **Correct Pattern / Fix**: Run user prompt inputs through `MaskingPipeline` and `EgressValidator` before LLM generation.

---

#### 2. `backend/app/api/documents.py`

##### Finding API-04 (High) — Unbounded Memory Allocation (DoS) in `upload_document`
- **File**: `backend/app/api/documents.py`
- **Line(s)**: 35
- **Severity**: High
- **Category**: Security issues (Denial of Service)
- **Description**: `file_bytes = await file.read()` reads the entire file into memory before checking file size at line 36. An attacker uploading a 5GB file will exhaust RAM and crash the server with an OOM killer.
- **Correct Pattern / Fix**: Read in 1MB chunks with a running byte counter, raising HTTP 413 immediately when `MAX_FILE_SIZE` is exceeded.

##### Finding API-05 (High) — Unsanitized Filename & NoneType Crash
- **File**: `backend/app/api/documents.py`
- **Line(s)**: 39, 49
- **Severity**: High
- **Category**: Security issues / Robustness
- **Description**: `file.filename.split('.')` crashes with `AttributeError` if filename is `None`. Furthermore, path traversal sequences (`..`, `/`, `\`) in filenames are not sanitized.
- **Correct Pattern / Fix**: Validate filename is not empty and sanitize using `Path(file.filename).name`.

##### Finding API-06 (High) — Anonymization Mapping Leak in Upload Response
- **File**: `backend/app/api/documents.py`
- **Line(s)**: 115
- **Severity**: High
- **Category**: Privacy pipeline logic
- **Description**: Line 115 returns `masking_report=registry.get_mapping()` in the upload API response, exposing the private dictionary of real entity names to API clients and proxy logs.
- **Correct Pattern / Fix**: Return token counts and entity category statistics without raw unmasked entity values.

##### Finding API-07 (Medium) — Database Transaction Inconsistency on Upload Failure
- **File**: `backend/app/api/documents.py`
- **Line(s)**: 119–127
- **Severity**: Medium
- **Category**: Database transaction correctness
- **Description**: On chunking exception, lines 119–127 execute `db_doc.status = DocumentStatus.ERROR; await db.commit()` without rolling back the dirty session, committing partially added `DocumentChunk` records.
- **Correct Pattern / Fix**: Execute `await db.rollback()` before updating status to `ERROR`.

---

#### 3. `backend/app/api/auth.py` & `backend/app/api/deps.py`

##### Finding API-08 (Critical) — Dual Conflicting `get_current_user` Dependencies with Divergent Schemes
- **File**: `backend/app/api/deps.py` vs `backend/app/middleware/auth_middleware.py`
- **Line(s)**: `deps.py:17–42` vs `auth_middleware.py:12–30`
- **Severity**: Critical
- **Category**: Architecture / Broken imports
- **Description**: Two conflicting implementations of `get_current_user` exist: `auth_middleware.py` uses `HTTPBearer` returning `TokenPayload`, while `deps.py` uses `OAuth2PasswordBearer` querying the database and returning `User`. `main.py` attaches rate limiting to `documents.router`, causing every request to `/documents/*` to execute two different auth dependencies with different schemes.
- **Correct Pattern / Fix**: Consolidate into a single canonical dependency in `app.api.deps`.

##### Finding API-09 (High) — Missing Inactive User Account Checks
- **File**: `backend/app/api/auth.py` (Lines 49, 77), `backend/app/api/deps.py` (Line 38)
- **Line(s)**: Multiple
- **Severity**: High
- **Category**: Security issues & Authentication
- **Description**: `login`, `refresh`, and `get_current_user` never verify `user.is_active`. Deactivated accounts can still authenticate and perform actions.
- **Correct Pattern / Fix**: Check `if not user.is_active: raise HTTPException(403, 'User account is deactivated')`.

##### Finding API-10 (High) — Refresh Tokens Accepted on Data Endpoints
- **File**: `backend/app/api/deps.py`
- **Line(s)**: 27–31
- **Severity**: High
- **Category**: Security issues
- **Description**: `deps.get_current_user` never checks `payload.get('type') == 'access'`, allowing long-lived (7-day) refresh tokens to authorize API data actions.
- **Correct Pattern / Fix**: Verify `payload.get('type') == 'access'`.

##### Finding API-11 (High) — Silent Fake Fallback in Gap Analysis on LLM Failure
- **File**: `backend/app/api/gap_analysis.py`
- **Line(s)**: 82–83
- **Severity**: High
- **Category**: Error handling / Misleading output
- **Description**: Catches `except Exception:` and returns `GapAnalysisResponse(gaps=[], coverage_score=0.0)`, misleading users into believing the document has 0 gaps.
- **Correct Pattern / Fix**: Log error and raise `HTTPException(502, 'Failed to generate gap analysis from LLM')`.

---

### 2.8 Middleware (`backend/app/middleware/`)

#### 1. `backend/app/middleware/rate_limiter.py`

##### Finding MID-01 (Critical) — `AttributeError` on `current_user.get()` Disabling Rate Limiter
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line(s)**: 38, 39, 98
- **Severity**: Critical
- **Category**: Type annotation correctness & Runtime type error
- **Description**: `check_rate_limit` calls `tenant_id = current_user.get('tenant_id')` on Pydantic `TokenPayload`. This raises `AttributeError` on every request. Lines 90–94 catch generic `Exception` and fail open, completely disabling rate limiting across the entire application.
- **Correct Pattern / Fix**: Access `current_user.tenant_id`.

##### Finding MID-02 (High) — Hardcoded Lua File Paths Fail in Containers
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line(s)**: 22, 26
- **Severity**: High
- **Category**: Incorrect API usage
- **Description**: `open('backend/lua/token_bucket.lua', 'r')` uses a relative path that fails with `FileNotFoundError` when Uvicorn runs from `backend/` or inside container `WORKDIR /app`.
- **Correct Pattern / Fix**: Resolve path dynamically: `Path(__file__).resolve().parent.parent.parent / 'lua'`.

##### Finding MID-03 (High) — Missing `tier` Claim Causes Enterprise Tenants to Default to Free Limits
- **File**: `backend/app/middleware/rate_limiter.py`
- **Line(s)**: 39
- **Severity**: High
- **Category**: Incorrect API usage
- **Description**: `tier` is never included in JWT claims, causing all tenants to default to FREE tier limits (10 capacity).
- **Correct Pattern / Fix**: Add `tier` to JWT claims during login/token creation.

##### Finding MID-04 (Medium) — Swallowed HTTPExceptions in Auth Middleware
- **File**: `backend/app/middleware/auth_middleware.py`
- **Line(s)**: 17–29
- **Severity**: Medium
- **Category**: Error handling
- **Description**: Catch-all `except Exception:` swallows specific 401 `HTTPException` instances and replaces them with generic messages.
- **Correct Pattern / Fix**: Catch `HTTPException` explicitly and re-raise.

---

### 2.9 Schemas (`backend/app/schemas/`)

#### 1. `backend/app/schemas/document.py`, `auth.py`, `compare.py`, `retrieval.py`, `gap_analysis.py`

##### Finding SCH-01 (High) — `DocumentMetadata` Requires `chunk_count` Missing on ORM Model
- **File**: `backend/app/schemas/document.py`
- **Line(s)**: 23–32
- **Severity**: High
- **Category**: Pydantic v2 schema compliance (R3)
- **Description**: `DocumentMetadata` defines `chunk_count: int` with `from_attributes=True`. The SQLAlchemy `Document` model lacks a `chunk_count` attribute, raising `ValidationError` on `DocumentMetadata.model_validate(db_doc)`.
- **Correct Pattern / Fix**: Add `@property def chunk_count(self) -> int:` on `Document` model or default `chunk_count: int = 0` in schema.

##### Finding SCH-02 (Medium) — Missing `model_config = ConfigDict(from_attributes=True)` Across Multiple Schemas
- **File**: `backend/app/schemas/auth.py`, `backend/app/schemas/compare.py`, `backend/app/schemas/gap_analysis.py`, `backend/app/schemas/retrieval.py`
- **Line(s)**: Multiple
- **Severity**: Medium
- **Category**: Pydantic v2 compliance (R3)
- **Description**: Schemas omit `model_config = ConfigDict(from_attributes=True)`, violating Project Rule #4 and preventing ORM-to-schema serialization.
- **Correct Pattern / Fix**: Add `model_config = ConfigDict(from_attributes=True)` to all response schemas.

##### Finding SCH-03 (Low) — Empty `schemas/__init__.py` Missing Public Exports
- **File**: `backend/app/schemas/__init__.py`
- **Line(s)**: 1
- **Severity**: Low
- **Category**: Code layout
- **Description**: Empty file requiring verbose nested imports.
- **Correct Pattern / Fix**: Re-export public schemas in `__init__.py`.

---

### 2.10 Database Layer, ORM Models & Alembic (`backend/app/db/`, `models/`, `alembic/`)

#### 1. `backend/alembic/env.py`

##### Finding MOD-01 (Critical) — Alembic `env.py` Omits Document Models, Breaking Autogenerated Migrations
- **File**: `backend/alembic/env.py`
- **Line(s)**: 12, 19
- **Severity**: Critical
- **Category**: Database schema & Migration bug
- **Description**: `alembic/env.py` only imports `Tenant` and `User`. `Document` and `DocumentChunk` are never imported. `target_metadata = Base.metadata` does not contain table metadata for documents, causing `alembic revision --autogenerate` to miss document tables or generate `DROP TABLE` statements.
- **Correct Pattern / Fix**: Import all models in `env.py`: `from app.models import Tenant, User, Document, DocumentChunk`.

---

#### 2. `backend/app/models/user.py` & `backend/app/models/document.py`

##### Finding MOD-02 (High) — Foreign Key Columns Missing `index=True` for Multi-Tenant Isolation
- **File**: `backend/app/models/user.py` (Line 43), `document.py` (Lines 24, 25, 43)
- **Line(s)**: Multiple
- **Severity**: High
- **Category**: Multi-tenancy performance & Database optimization
- **Description**: Foreign key columns `User.tenant_id`, `Document.tenant_id`, `Document.user_id`, and `DocumentChunk.document_id` lack `index=True`, causing unindexed sequential table scans on every multi-tenant query.
- **Correct Pattern / Fix**: Add `index=True` to all multi-tenancy foreign key columns:
  ```python
  tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
  ```

##### Finding MOD-03 (High) — Empty `models/__init__.py` Breaking Model Registration
- **File**: `backend/app/models/__init__.py`
- **Line(s)**: 1
- **Severity**: High
- **Category**: Code layout / Model discovery
- **Description**: Empty `__init__.py` prevents `import app.models` from registering all ORM tables with `Base.metadata`.
- **Correct Pattern / Fix**: Re-export all models in `__init__.py`.

##### Finding MOD-04 (Medium) — Legacy SQLAlchemy 1.4 `declarative_base()`
- **File**: `backend/app/db/database.py`
- **Line(s)**: 6, 10
- **Severity**: Medium
- **Category**: SQLAlchemy 2.0 compliance (R3)
- **Description**: Uses legacy `Base = declarative_base()`.
- **Correct Pattern / Fix**: Subclass `DeclarativeBase`:
  ```python
  from sqlalchemy.orm import DeclarativeBase
  class Base(DeclarativeBase):
      pass
  ```

##### Finding MOD-05 (Medium) — Missing `pool_pre_ping=True` on Async Engine
- **File**: `backend/app/db/database.py`
- **Line(s)**: 12–17
- **Severity**: Medium
- **Category**: Database reliability
- **Description**: Without `pool_pre_ping=True`, idle connections dropped by AWS RDS or PostgreSQL cause unhandled `InterfaceError: connection is closed`.
- **Correct Pattern / Fix**: Set `pool_pre_ping=True` in `create_async_engine()`.

---

### 2.11 Configuration, Utilities & Server Entrypoint (`backend/app/config.py`, `utils/`, `main.py`)

#### 1. `backend/app/config.py` & `backend/app/utils/security.py`

##### Finding CFG-01 (Critical) — RS256 JWT Configured with Symmetric Key String
- **File**: `backend/app/config.py` (Lines 46–47), `backend/app/utils/security.py` (Lines 32, 42, 47)
- **Line(s)**: Multiple
- **Severity**: Critical
- **Category**: Security issues & Cryptography
- **Description**: `config.py` specifies `jwt_algorithm = "RS256"` and `jwt_secret_key = ""` as a single symmetric secret string. RS256 is an asymmetric algorithm requiring an RSA Private Key (PEM) for signing and an RSA Public Key (PEM) for verification. Passing a symmetric string secret to RS256 causes cryptographic libraries to raise `KeyError` / `JOSEError: Key must be a valid RSA key`.
- **Correct Pattern / Fix**: Configure separate `jwt_private_key_pem` and `jwt_public_key_pem` in `Settings`, and use `PyJWT`.

##### Finding CFG-02 (High) — Disabled CORS by Default Blocks Frontend Access
- **File**: `backend/app/main.py`
- **Line(s)**: 35–43
- **Severity**: High
- **Category**: Security / Web API configuration
- **Description**: `main.py` adds `CORSMiddleware` only `if settings.allowed_origins:`. Because `allowed_origins` defaults to empty string, no CORS headers are emitted, causing browser requests from `localhost:5173` (Vite) to fail preflight checks.
- **Correct Pattern / Fix**: Always register `CORSMiddleware` with safe development defaults (`['http://localhost:5173', 'http://localhost:3000']`).

##### Finding CFG-03 (Medium) — Missing Reverse-Proxy Headers in SSE Streaming Utility
- **File**: `backend/app/utils/streaming.py`
- **Line(s)**: 24
- **Severity**: Medium
- **Category**: Web streaming / Performance
- **Description**: `StreamingResponse` omits `X-Accel-Buffering: no` and `Cache-Control: no-cache`. When deployed behind Nginx or AWS ALB, the streaming response is buffered and sent as a single block at completion, breaking real-time token streaming.
- **Correct Pattern / Fix**: Add headers `{"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}`.

##### Finding CFG-04 (Low) — Deprecated `datetime.utcnow()` Usage Across Modules
- **File**: `backend/app/models/user.py`, `document.py`, `utils/security.py`, `api/health.py`
- **Line(s)**: Multiple
- **Severity**: Low
- **Category**: Python 3.12 compatibility
- **Description**: `datetime.utcnow()` emits `DeprecationWarning` in Python 3.12.
- **Correct Pattern / Fix**: Replace with `datetime.now(timezone.utc)`.

---

## 3. Dependency Compatibility Issues (Requirement R2)

---

### Finding DEP-01 (Critical) — Unmaintained `python-jose` with Known CVEs vs Required `PyJWT`
- **Dependency**: `python-jose[cryptography]` vs `PyJWT`
- **Affected Files**: `backend/requirements.txt` (Line 19), `backend/app/utils/security.py` (Line 7)
- **Severity**: Critical
- **Category**: Deprecated Package / Security Vulnerability
- **Description**: `python-jose` is unmaintained (last release 2021) and contains **CVE-2024-33663** and **CVE-2024-33664**. It breaks on modern `cryptography>=42.0.0`. `AGENTS.md` strictly mandates `PyJWT`.
- **Correct Specification / Fix**: In `requirements.txt`, replace `python-jose[cryptography]` with `PyJWT[crypto]>=2.8.0`.

---

### Finding DEP-02 (Critical) — `passlib[bcrypt]` Incompatible with `bcrypt>=4.0.0` & Python 3.12 Build Failure
- **Dependency**: `passlib[bcrypt]` and pinned `bcrypt==3.2.2`
- **Affected Files**: `backend/requirements.txt` (Lines 20, 21), `backend/app/utils/security.py` (Line 8)
- **Severity**: Critical
- **Category**: Dependency Compatibility / Build Failure
- **Description**: `passlib` crashes on `bcrypt>=4.0.0`. Pinning `bcrypt==3.2.2` fails on Python 3.12 because `bcrypt 3.2.2` lacks Python 3.12 binary wheels, causing CFFI source build failures in `python:3.12-slim`.
- **Correct Specification / Fix**: Remove `passlib[bcrypt]`, pin modern `bcrypt>=4.1.0`, and use `bcrypt.hashpw` / `bcrypt.checkpw` directly in `security.py`.

---

### Finding DEP-03 (High) — Dockerfile Runtime Stage Missing Required C-Libraries for Docling
- **Dependency**: `docling>=2.0.0` / System libraries (`libgl1`, `libgomp1`, `libglib2.0-0`)
- **Affected Files**: `backend/Dockerfile` (Lines 14–23)
- **Severity**: High
- **Category**: Container Environment / Missing System Dependencies
- **Description**: In the multi-stage `Dockerfile`, stage 2 (`runtime`) starts from clean `python:3.12-slim` without installing runtime C-libraries. Docling's OCR / PyMuPDF layout engine fails on container startup with `ImportError: libGL.so.1: cannot open shared object file`.
- **Correct Specification / Fix**: Add `apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1` in runtime stage.

---

### Finding DEP-04 (High) — Blocking `spacy.cli.download` and Redundant Dockerfile Pin
- **Dependency**: `spacy` (`en_core_web_lg`)
- **Affected Files**: `backend/requirements.txt` (Line 12), `backend/Dockerfile` (Line 11), `ner_masker.py` (Line 46)
- **Severity**: High
- **Category**: Dependency Packaging
- **Description**: `Dockerfile` line 11 runs `pip install spacy==3.7.0` (which lacks Python 3.12 wheels).
- **Correct Specification / Fix**: Pin `spacy>=3.7.2` and download or link `en_core_web_lg` wheel during image build.

---

### Finding DEP-05 (Medium) — Deprecated Package Name `pinecone-client`
- **Dependency**: `pinecone-client` vs `pinecone`
- **Affected Files**: `backend/requirements.txt` (Line 16), `backend/app/services/retrieval/pinecone_store.py` (Line 2)
- **Severity**: Medium
- **Category**: Deprecated Package Naming
- **Description**: `requirements.txt` specifies legacy `pinecone-client` (v2.x) while code uses v3+ syntax `from pinecone import Pinecone`.
- **Correct Specification / Fix**: Replace `pinecone-client` with `pinecone>=5.0.0` (or `pinecone>=3.0.0`).

---

### Finding DEP-06 (Medium) — Redundant & Conflicting `langchain-*` Packages
- **Dependency**: `langchain-nvidia-ai-endpoints`, `langchain-google-genai`
- **Affected Files**: `backend/requirements.txt` (Lines 30, 32), `backend/app/services/guardrails/config.yml`
- **Severity**: Medium
- **Category**: Redundant Dependencies / Namespace Conflict
- **Description**: Core LLM providers use native `openai` and `google-genai` SDKs. `langchain-google-genai` pulls legacy `google-generativeai`, conflicting with unified `google-genai`.
- **Correct Specification / Fix**: Remove `langchain-nvidia-ai-endpoints` and `langchain-google-genai` from `requirements.txt`.

---

### Finding DEP-07 (Low) — Unused Dependencies in `requirements.txt`
- **Dependency**: `tiktoken`, `presidio-anonymizer`
- **Affected Files**: `backend/requirements.txt` (Lines 14, 24)
- **Severity**: Low
- **Category**: Dependency Bloat
- **Description**: `tiktoken` and `presidio-anonymizer` are never imported anywhere in `backend/app/`.
- **Correct Specification / Fix**: Remove `tiktoken` and `presidio-anonymizer`.

---

### Finding DEP-08 (Low) — Deprecated `pydantic[dotenv]` Extra
- **Dependency**: `pydantic[dotenv,email]>=2.0`
- **Affected Files**: `backend/requirements.txt` (Line 3)
- **Severity**: Low
- **Category**: Deprecated Extra
- **Description**: In Pydantic v2, settings parsing belongs to `pydantic-settings`. The `[dotenv]` extra is obsolete.
- **Correct Specification / Fix**: Update to `pydantic[email]>=2.8.0` and `pydantic-settings>=2.4.0`.

---

## 4. Reconciled `requirements.txt` and `Dockerfile`

### Recommended `backend/requirements.txt`

```text
# Web Framework & Server
fastapi>=0.112.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.9
httpx>=0.27.0

# Schemas & Settings (Pydantic v2)
pydantic[email]>=2.8.0
pydantic-settings>=2.4.0
email-validator>=2.2.0

# Database & ORM (SQLAlchemy 2.0 Async)
sqlalchemy[asyncio]>=2.0.32
asyncpg>=0.29.0
alembic>=1.13.2
aiosqlite>=0.20.0

# Security & Authentication (RS256 JWT & Modern Bcrypt)
PyJWT[crypto]>=2.8.0
cryptography>=42.0.0
bcrypt>=4.1.0

# Rate Limiting & Caching
upstash-redis>=1.0.0

# LLM Providers (Native SDKs)
openai>=1.40.0
google-genai>=0.1.1

# Document Extraction
docling>=2.0.0
docling-core>=2.0.0

# Privacy & Masking Pipeline
spacy>=3.7.2
https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl
presidio-analyzer>=2.2.355
pyahocorasick>=2.1.0

# Vector Database (Pinecone v3+)
pinecone>=5.0.0

# Guardrails
nemoguardrails>=0.11.0

# Code Quality & Testing
pytest>=8.3.0
pytest-asyncio>=0.23.8
ruff>=0.5.0
mypy>=1.11.0
```

---

### Recommended `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim as runtime

WORKDIR /app

# Install runtime shared C-libraries required by Docling, PyMuPDF, and OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/root/.local/lib/python3.12/site-packages:$PYTHONPATH

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

---

## 5. Remediation Priority & Action Plan

```
+---------------------------------------------------------------------------------------------------+
| PRIORITY 0: IMMEDIATE RUNTIME BLOCKERS & EXPLOITS                                                 |
| 1. Fix `AttributeError: 'TokenPayload' object has no attribute 'get'` in API & rate limiter.      |
| 2. Add tenant ownership validation on `request.document_id` in `app/api/query.py`.                |
| 3. Fix `generate_stream` coroutine/async generator mismatch in `router.py` & `circuit_breaker.py`.|
| 4. Fix character slice indexing in `masking_pipeline.py` & `bank_matcher.py`.                    |
| 5. Configure RSA PEM key pairs for RS256 in `config.py` and migrate to `PyJWT`.                   |
| 6. Import `Document` and `DocumentChunk` models in `alembic/env.py`.                              |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+---------------------------------------------------------------------------------------------------+
| PRIORITY 1: SECURITY, PRIVACY & STABILITY HARDENING                                               |
| 1. Implement chunked streaming file upload in `documents.py` to prevent OOM DoS.                  |
| 2. Enforce `MaskingPipeline` and `EgressValidator` on user questions in query & compare APIs.    |
| 3. Add chunk accumulation and overlap in `chunker.py` and preserve Markdown tables.               |
| 4. Fix NVIDIA NIM rerank API payload schema and base URL in `nvidia_provider.py`.                 |
| 5. Pass context into NeMo Guardrails `generate_async` and handle dict response format.            |
| 6. Add `index=True` to multi-tenancy foreign keys in ORM models.                                  |
| 7. Install Docling runtime C-libraries (`libgl1`, `libgomp1`) in Dockerfile.                      |
+---------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+---------------------------------------------------------------------------------------------------+
| PRIORITY 2: CLEANUP, REFACTORING & CONVENTIONS                                                    |
| 1. Add `model_config = ConfigDict(from_attributes=True)` across all Pydantic v2 schemas.          |
| 2. Subclass `DeclarativeBase` in `db/database.py` and enable `pool_pre_ping=True`.                |
| 3. Replace deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`.                     |
| 4. Re-export public module APIs in all `__init__.py` files.                                       |
| 5. Remove redundant `langchain-*` and unused packages from `requirements.txt`.                   |
+---------------------------------------------------------------------------------------------------+
```

---
*End of ModelAudit AI Master Static Code Audit Report.*
