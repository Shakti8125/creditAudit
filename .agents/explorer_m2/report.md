# ModelAudit AI — Backend Code Audit Report: LLM Providers & NeMo Guardrails Services

**Auditor**: Explorer M2  
**Date**: 2026-08-28  
**Scope**: `backend/app/services/llm/` and `backend/app/services/guardrails/`  
**Integrity Mode**: Read-Only Static Analysis  

---

## 1. Executive Summary

This report delivers a thorough static code review of the LLM Providers and NeMo Guardrails services of ModelAudit AI. The audit evaluated API compatibility with latest official SDKs (`openai` 1.40+, `google-genai`, `nemoguardrails` 0.11+), async/await streaming execution semantics, circuit breaker state-machine integrity, multi-provider routing and fallback mechanics, and Colang 2.0 guardrail definitions.

A total of **16 distinct bugs and structural issues** were identified across 10 files in scope:
- **Critical**: 6
- **High**: 5
- **Medium**: 4
- **Low**: 1

### Bug Summary by Severity & Category

| Severity | Count | Primary Categories |
|---|---|---|
| **Critical** | 6 | Async/await correctness, Incorrect API usage, Privacy / Guardrails logic |
| **High** | 5 | Multi-provider routing / fallback, Resource management, Concurrency / Race conditions |
| **Medium** | 4 | Code conventions, Schema validation, Type annotation correctness |
| **Low** | 1 | Missing public exports / initialization |
| **Total** | **16** | |

---

## 2. Comprehensive Findings Index

| ID | File | Line(s) | Severity | Category | Brief Description |
|---|---|---|---|---|---|
| **LLM-01** | `backend/app/services/llm/router.py` | 133–145 | **Critical** | Async/await correctness | Coroutine / Async Generator crash in `generate_stream` |
| **LLM-02** | `backend/app/services/llm/circuit_breaker.py` | 51–63 | **Critical** | Async/await correctness | `CircuitBreaker.call` crashes on async generator methods |
| **LLM-03** | `backend/app/services/llm/nvidia_provider.py` | 137–143 | **Critical** | Incorrect API usage | Invalid payload format and base_url path truncation in NVIDIA NIM rerank API |
| **LLM-04** | `backend/app/services/guardrails/guardrails_service.py` | 47–60, 101 | **Critical** | Incorrect API usage | Dict response compared with string and assigned to `str` field |
| **LLM-05** | `backend/app/services/guardrails/guardrails_service.py` | 34, 47–54 | **Critical** | Incorrect API usage | Context and retrieved contexts never passed to NeMo Guardrails execution |
| **LLM-06** | `backend/app/services/guardrails/rails.co` | 43–48 | **Critical** | Incorrect API usage | Undefined bot utterance `bot refuse to respond` crashes Colang flow |
| **LLM-07** | `backend/app/services/llm/router.py` | 101–118 | **High** | Incorrect API usage | Multi-provider router lacks fallback / failover retry logic |
| **LLM-08** | `backend/app/api/query.py` (and compare/gap/reg) | 22 (query.py) | **High** | Incorrect API usage | Router re-instantiated per request; wipes latency history and circuit breaker state |
| **LLM-09** | `backend/app/services/llm/circuit_breaker.py` | 26–50 | **High** | Async/await correctness | Lack of async lock causing race condition during HALF_OPEN state |
| **LLM-10** | `backend/app/services/llm/nvidia_provider.py` | 71–78 | **High** | Resource management | Unmanaged `httpx.AsyncClient` created in `__init__` with no close lifecycle |
| **LLM-11** | `backend/app/services/guardrails/config.yml` | 1–14 | **High** | Incorrect API usage | Multiple `type: main` models defined in `config.yml` |
| **LLM-12** | `backend/app/services/guardrails/actions.py` | 88–114 | **Medium** | Incorrect API usage | `check_placeholder_integrity_action` is a no-op returning `True` unconditionally |
| **LLM-13** | `backend/app/services/guardrails/actions.py` | 63–85 | **Medium** | Incorrect API usage | Hallucination metric distorted by stop words and splits comma-separated financial numbers |
| **LLM-14** | `backend/app/services/llm/base_provider.py` | 20, 25, 30, 35 | **Medium** | Type annotation correctness | Missing default parameter values in base class method signatures |
| **LLM-15** | `backend/app/services/llm/base_provider.py` | 1, 5, 10 | **Medium** | Schema validation | Missing `from __future__ import annotations` and Pydantic v2 `ConfigDict` |
| **LLM-16** | `backend/app/services/guardrails/__init__.py` | 1 | **Low** | Broken imports / packaging | Empty `__init__.py` missing package exports |

---

## 3. Detailed Per-File Findings

### 3.1 `backend/app/services/llm/router.py`

#### Finding LLM-01
- **File**: `backend/app/services/llm/router.py`
- **Line**: 122–146
- **Severity**: **Critical**
- **Category**: Async/await correctness
- **Description**: 
  `LLMRouter.generate_stream` is declared with `async def`. Inside the method, it attempts `stream = await cb.call(func, ...)` and then executes `return _yield_and_record()`.
  This creates two fatal runtime failures:
  1. An `async def` function returning an async generator object `_yield_and_record()` returns a `Coroutine` resolving to an async generator. Callers invoking `async for chunk in router.generate_stream(...)` will encounter `TypeError: 'coroutine' object is not an async iterable`.
  2. The call `await cb.call(func, ...)` passes `func` (which is an async generator function `nvidia.generate_stream` or `gemini.generate_stream`). Inside `cb.call`, executing `await func(...)` raises `TypeError: object async_generator can't be used in 'await' expression`.
- **Correct Pattern / Fix**:
  Implement `generate_stream` directly as an async generator using `async def` and `yield` (without returning a nested generator object). Stream tokens through an async wrapper that records latency and trips the circuit breaker on error:
  ```python
  async def generate_stream(
      self,
      prompt: str,
      system_prompt: str | None = None,
      temperature: float = 0.7,
      max_tokens: int = 1024
  ) -> AsyncIterator[str]:
      decision = self.get_routing_decision()
      provider_name = decision.provider
      provider_inst = self.providers[provider_name]
      cb = self.circuit_breakers[provider_name]
      
      start_time = time.time()
      try:
          async for chunk in provider_inst.generate_stream(
              prompt=prompt,
              system_prompt=system_prompt,
              temperature=temperature,
              max_tokens=max_tokens
          ):
              yield chunk
          latency_ms = (time.time() - start_time) * 1000
          self._record_latency(provider_name, latency_ms)
          cb.record_success()
      except Exception as e:
          cb.record_failure()
          logger.error(f"Streaming error on {provider_name}: {e}")
          # Optional fallback to secondary provider
          raise e
  ```

---

#### Finding LLM-07
- **File**: `backend/app/services/llm/router.py`
- **Line**: 101–118
- **Severity**: **High**
- **Category**: Incorrect API usage
- **Description**: 
  `LLMRouter._execute_routed` selects a provider via `get_routing_decision()`. If that provider fails during execution (`await cb.call(func, ...)`), the exception is logged and immediately re-raised. The router never attempts to fail over / fall back to the secondary provider (e.g., from NVIDIA to Gemini). This violates the core design requirement for multi-provider resilience.
- **Correct Pattern / Fix**:
  Implement automatic fallback in `_execute_routed`:
  ```python
  async def _execute_routed(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
      providers_to_try = []
      decision = self.get_routing_decision()
      primary = decision.provider
      providers_to_try.append(primary)
      secondary = "gemini" if primary == "nvidia" else "nvidia"
      if self.circuit_breakers[secondary].get_state() != CircuitState.OPEN:
          providers_to_try.append(secondary)
          
      last_error = None
      for provider_name in providers_to_try:
          provider_inst = self.providers[provider_name]
          cb = self.circuit_breakers[provider_name]
          func = getattr(provider_inst, method_name)
          start_time = time.time()
          try:
              result = await cb.call(func, *args, **kwargs)
              latency_ms = (time.time() - start_time) * 1000
              self._record_latency(provider_name, latency_ms)
              return result
          except Exception as e:
              last_error = e
              logger.warning(f"Provider {provider_name} failed for {method_name}: {e}. Retrying fallback...")
              
      raise last_error or AllProvidersUnavailableError("All available providers failed execution.")
  ```

---

### 3.2 `backend/app/services/llm/circuit_breaker.py`

#### Finding LLM-02
- **File**: `backend/app/services/llm/circuit_breaker.py`
- **Line**: 51–63
- **Severity**: **Critical**
- **Category**: Async/await correctness
- **Description**: 
  `CircuitBreaker.call` expects `func(*args, **kwargs)` to return a `Coroutine` and executes `result = await func(*args, **kwargs)`. When wrapping streaming methods (`generate_stream`), `func` is an async generator function returning an `async_generator` object. Awaiting an async generator raises `TypeError: object async_generator can't be used in 'await' expression`.
  Furthermore, `self.record_success()` is called immediately on line 59 before any stream chunks are read.
- **Correct Pattern / Fix**:
  Separate regular coroutine execution from async generator streaming execution, or provide a dedicated `call_stream` context/generator wrapper in `CircuitBreaker`.

---

#### Finding LLM-09
- **File**: `backend/app/services/llm/circuit_breaker.py`
- **Line**: 26–50
- **Severity**: **High**
- **Category**: Async/await correctness
- **Description**: 
  `CircuitBreaker` manages state transitions (`CLOSED` -> `OPEN` -> `HALF_OPEN` -> `CLOSED`) and counters without synchronization. In an async web framework handling concurrent requests:
  1. Multiple concurrent requests entering during `HALF_OPEN` state will all pass through simultaneously rather than testing a single probe request.
  2. Race conditions can occur where one request fails and trips the breaker to `OPEN` while a concurrent request succeeds and resets it to `CLOSED`.
- **Correct Pattern / Fix**:
  Add an `asyncio.Lock()` to synchronize state transitions and limit concurrent trial requests in `HALF_OPEN`:
  ```python
  class CircuitBreaker:
      def __init__(self, provider_name: str, max_failures: int = 5, reset_timeout: int = 30):
          self.provider_name = provider_name
          self.max_failures = max_failures
          self.reset_timeout = reset_timeout
          self.state = CircuitState.CLOSED
          self.failures = 0
          self.last_failure_time = 0.0
          self._lock = asyncio.Lock()
          self._half_open_in_flight = False
  ```

---

### 3.3 `backend/app/services/llm/nvidia_provider.py`

#### Finding LLM-03
- **File**: `backend/app/services/llm/nvidia_provider.py`
- **Line**: 137–143
- **Severity**: **Critical**
- **Category**: Incorrect API usage
- **Description**: 
  The `NvidiaProvider.rerank` method fails with two critical bugs when communicating with NVIDIA NIM:
  1. **Payload Schema Mismatch**: The official NVIDIA NIM Reranking API (`nvidia/nv-rerankqa-mistral-4b-v3` at `/v1/ranking`) requires `query` to be an object `{"text": query}` and `passages` to be a list of objects `[{"text": p} for p in passages]`. Passing plain strings causes HTTP 422 Unprocessable Entity.
  2. **URL Path Resolution Bug in `httpx`**: `self.httpx_client` is initialized with `base_url="https://integrate.api.nvidia.com/v1"`. Invoking `self.httpx_client.post("/ranking", ...)` with a leading slash causes RFC 3986 URL resolution to strip `/v1` and target `https://integrate.api.nvidia.com/ranking` (HTTP 404 Not Found).
- **Correct Pattern / Fix**:
  Format the payload as structured objects and use relative endpoint `ranking`:
  ```python
  async def rerank(self, query: str, passages: list[str], top_n: int = 5) -> list[RerankResult]:
      async def _call():
          payload = {
              "model": NVIDIA_RERANKING_MODEL,
              "query": {"text": query},
              "passages": [{"text": p} for p in passages],
              "truncate": "END"
          }
          # Use "ranking" without leading slash so /v1 prefix is preserved
          response = await self.httpx_client.post("ranking", json=payload)
          response.raise_for_status()
          return response.json()
          
      data = await _execute_with_retry(_call)
      results = []
      for ranking in data.get("rankings", [])[:top_n]:
          idx = ranking["index"]
          results.append(RerankResult(
              index=idx,
              score=ranking["logit"],
              text=passages[idx]
          ))
      return results
  ```

---

#### Finding LLM-10
- **File**: `backend/app/services/llm/nvidia_provider.py`
- **Line**: 71–78
- **Severity**: **High**
- **Category**: Resource management
- **Description**: 
  `self.httpx_client = httpx.AsyncClient(...)` is instantiated inside `__init__`, but `NvidiaProvider` defines no `close()` / `aclose()` lifecycle method, nor is it registered with FastAPI application lifespan hooks. This leaves persistent HTTP connections open, triggering resource leak warnings and event loop closure issues during testing/shutdown.
- **Correct Pattern / Fix**:
  Provide an explicit `aclose()` coroutine or use a shared HTTP client session managed in application lifespan:
  ```python
  async def aclose(self) -> None:
      await self.httpx_client.aclose()
  ```

---

### 3.4 `backend/app/services/guardrails/guardrails_service.py`

#### Finding LLM-04
- **File**: `backend/app/services/guardrails/guardrails_service.py`
- **Line**: 47–60, 101
- **Severity**: **Critical**
- **Category**: Incorrect API usage
- **Description**: 
  When invoking `response = await self.rails.generate_async(messages=messages)`, NeMo Guardrails returns a dictionary (e.g. `{"role": "assistant", "content": "..."}`), NOT a string.
  The code attempts string equality checks directly against the dictionary:
  `if response == "I am ModelAudit AI...":`
  These comparisons will ALWAYS evaluate to `False`.
  On line 101, `GuardrailsResult(response=response, ...)` passes the dictionary to a field typed as `str | None`, causing Pydantic validation errors or passing dicts into string pipelines.
- **Correct Pattern / Fix**:
  Extract the assistant content string before performing equality checks:
  ```python
  res = await self.rails.generate_async(messages=messages)
  if isinstance(res, dict):
      content = res.get("content", "")
  else:
      content = str(res) if res is not None else ""
      
  if content == "I am ModelAudit AI, specialized in credit risk model validation and CBUAE MMG regulatory compliance. I cannot help with that topic.":
      return GuardrailsResult(
          response=None,
          blocked=True,
          block_reason="Off-topic query",
          rail_type="dialog"
      )
  ```

---

#### Finding LLM-05
- **File**: `backend/app/services/guardrails/guardrails_service.py`
- **Line**: 34, 47–54
- **Severity**: **Critical**
- **Category**: Incorrect API usage
- **Description**: 
  `generate_with_guardrails(self, prompt: str, context: str, retrieved_contexts: list[str])` accepts `context` and `retrieved_contexts`, but NEVER passes them to `self.rails.generate_async()`.
  Consequently, custom actions like `check_hallucination_action` that look up `context.get("retrieved_contexts")` receive an empty list and always return `0.0` (0% hallucination), effectively bypassing output grounding validation entirely.
- **Correct Pattern / Fix**:
  Pass the context dictionary into `generate_async`:
  ```python
  response = await self.rails.generate_async(
      messages=messages,
      context={
          "context": context,
          "retrieved_contexts": retrieved_contexts
      }
  )
  ```

---

### 3.5 `backend/app/services/guardrails/rails.co` & `config.yml`

#### Finding LLM-06
- **File**: `backend/app/services/guardrails/rails.co`
- **Line**: 43–48
- **Severity**: **Critical**
- **Category**: Incorrect API usage
- **Description**: 
  In `rails.co`:
  ```colang
  define flow check hallucination against context
    $hallucination_prob = execute check_hallucination_action
    if $hallucination_prob > 0.7
      bot refuse to respond
      stop
  ```
  The bot utterance `bot refuse to respond` is NEVER defined in `rails.co`. In Colang, referencing an undefined utterance causes a runtime flow execution error.
- **Correct Pattern / Fix**:
  Define `bot refuse to respond` in `rails.co`:
  ```colang
  define bot refuse to respond
    "I'm sorry, but I cannot verify this answer against the provided credit documentation."
  ```

---

#### Finding LLM-11
- **File**: `backend/app/services/guardrails/config.yml`
- **Line**: 1–14
- **Severity**: **High**
- **Category**: Incorrect API usage
- **Description**: 
  `config.yml` defines two separate models under `models:` both configured with `type: main` (one for `langchain-nvidia-ai-endpoints` and one for `langchain-google-genai`). NeMo Guardrails requires exactly one `type: main` model in `config.yml`. Having duplicates causes configuration parsing conflicts.
  Additionally, `colang_version: "2.x"` is omitted, causing NeMo Guardrails to default to Colang 1.0 parsing mode.
- **Correct Pattern / Fix**:
  Specify `colang_version: "2.x"` and define a single main model (or configure model providers according to NeMo Guardrails multi-model schema):
  ```yaml
  colang_version: "2.x"

  models:
    - type: main
      engine: openai
      model: nvidia/llama-3.1-nemotron-70b-instruct
      parameters:
        base_url: https://integrate.api.nvidia.com/v1
        temperature: 0.1
  ```

---

### 3.6 API Routes Singleton Usage (`app/api/`)

#### Finding LLM-08
- **File**: `backend/app/api/query.py` (Line 22), `backend/app/api/compare.py` (Line 63), `backend/app/api/gap_analysis.py` (Line 54), `backend/app/api/regulatory.py` (Line 20)
- **Line**: Multiple
- **Severity**: **High**
- **Category**: Incorrect API usage
- **Description**: 
  Each API endpoint creates a local instance `llm_router = LLMRouter()` on every incoming request.
  This destroys the router's state across requests:
  - `latency_history` is wiped, making latency-based routing always return `0.0ms` and fall back to default logic.
  - `circuit_breakers` are reset to `CLOSED` with 0 failures on every request. If a provider is down, every new request creates a fresh circuit breaker and hammers the failing provider again, completely defeating circuit breaking.
- **Correct Pattern / Fix**:
  Expose a shared singleton router in `app/api/deps.py` and inject via FastAPI `Depends()`:
  ```python
  # in app/api/deps.py
  from app.services.llm.router import LLMRouter

  _router_instance = LLMRouter()

  def get_llm_router() -> LLMRouter:
      return _router_instance
  ```

---

### 3.7 `backend/app/services/guardrails/actions.py`

#### Finding LLM-12
- **File**: `backend/app/services/guardrails/actions.py`
- **Line**: 88–114
- **Severity**: **Medium**
- **Category**: Incorrect API usage
- **Description**: 
  `check_placeholder_integrity_action` iterates over regex matches with a `pass` statement and unconditionally returns `True` at the end. It never validates or flags invalid/broken placeholders or unmasked entity leaks.
- **Correct Pattern / Fix**:
  Validate placeholder pattern format and verify that any brackets match allowed masked entity patterns (e.g. `r'^\[(BANK|ORG|PERSON|PRODUCT|SYSTEM|METRIC|LOC)_\d+\]$'`):
  ```python
  @action(name="check_placeholder_integrity_action")
  async def check_placeholder_integrity_action(context: dict[str, Any] | None = None) -> bool:
      if not context:
          return True
      text = context.get("last_bot_message", "")
      if not text:
          return True
          
      # Find all bracketed tokens
      tokens = re.findall(r'\[([^\]]+)\]', text)
      for token in tokens:
          # If it starts with known entity types but lacks a numeric ID, flag as broken
          if re.match(r'^(BANK|ORG|PERSON|PRODUCT|SYSTEM|METRIC|LOC)$', token):
              return False
          if re.match(r'^(BANK|ORG|PERSON|PRODUCT|SYSTEM|METRIC|LOC)_$', token):
              return False
      return True
  ```

---

#### Finding LLM-13
- **File**: `backend/app/services/guardrails/actions.py`
- **Line**: 63–85
- **Severity**: **Medium**
- **Category**: Incorrect API usage
- **Description**: 
  In `check_hallucination_action`:
  1. The tokenization regex `r'\b(?:[A-Za-z]+|\d+(?:\.\d+)?)\b'` splits comma-separated financial numbers like `1,250,000` into `['1', '250', '000']`, violating Project Rule #10 ("Financial numbers: Commas in numbers (e.g., `1,250,000`) must be preserved during text processing. Never split on commas").
  2. Word overlap is computed over all words including common English stop words (`the`, `is`, `of`, `to`, `in`, `and`). Stop words constitute 40–50% of typical output, causing fabricated responses to easily exceed the 30% overlap threshold.
- **Correct Pattern / Fix**:
  Strip stop words from overlap calculation and tokenize preserving comma-formatted numbers:
  ```python
  STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to", "for", "of", "and", "or", "by", "with", "as", "from", "that", "this"}

  words = re.findall(r'\b(?:[A-Za-z]+|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\b', bot_message.lower())
  content_words = [w for w in words if w not in STOP_WORDS]
  if not content_words:
      return 0.0
  overlap_count = sum(1 for word in set(content_words) if word in context_text)
  overlap_percentage = overlap_count / len(set(content_words))
  return 1.0 - overlap_percentage
  ```

---

### 3.8 `backend/app/services/llm/base_provider.py`

#### Finding LLM-14
- **File**: `backend/app/services/llm/base_provider.py`
- **Line**: 20, 25, 30, 35
- **Severity**: **Medium**
- **Category**: Type annotation correctness
- **Description**: 
  Abstract method signatures in `BaseLLMProvider` lack default parameter values for optional parameters (e.g. `system_prompt: str | None`, `temperature: float`, `max_tokens: int`, `json_schema: dict | None`). Subclasses `NvidiaProvider` and `GeminiProvider` mirror these signatures without defaults, making direct calls such as `provider.generate(prompt)` raise `TypeError: missing 4 required positional arguments`.
- **Correct Pattern / Fix**:
  Add sensible defaults to abstract base class and subclass method definitions:
  ```python
  @abstractmethod
  async def generate(
      self,
      prompt: str,
      system_prompt: str | None = None,
      temperature: float = 0.7,
      max_tokens: int = 1024,
      json_schema: dict | None = None
  ) -> str:
      ...
  ```

---

#### Finding LLM-15
- **File**: `backend/app/services/llm/base_provider.py`
- **Line**: 1, 5, 10
- **Severity**: **Medium**
- **Category**: Schema validation
- **Description**: 
  1. Missing `from __future__ import annotations` (violates Project Rule #3).
  2. `RerankResult` and `ProviderHealth` do not include `model_config = ConfigDict(...)` (violates Project Rule #4).
- **Correct Pattern / Fix**:
  Add `from __future__ import annotations` and configure Pydantic models with `ConfigDict(from_attributes=True)`.

---

### 3.9 `backend/app/services/guardrails/__init__.py`

#### Finding LLM-16
- **File**: `backend/app/services/guardrails/__init__.py`
- **Line**: 1
- **Severity**: **Low**
- **Category**: Broken imports / packaging
- **Description**: 
  The file is empty (0 bytes) and does not expose `GuardrailsService`, `GuardrailsResult`, or actions for external consumption.
- **Correct Pattern / Fix**:
  Export module public interface in `__init__.py`:
  ```python
  from .guardrails_service import GuardrailsService, GuardrailsResult

  __all__ = ["GuardrailsService", "GuardrailsResult"]
  ```

---

## 4. Dependency Compatibility & Redundancies (R2 Findings)

Review of `backend/requirements.txt`:
1. **Redundant & Deprecated LangChain Packages**:
   - `langchain-nvidia-ai-endpoints` (line 30) and `langchain-google-genai` (line 32) are included alongside the primary SDKs `openai>=1.40.0` and `google-genai`.
   - The primary LLM services in `backend/app/services/llm/` use direct SDK clients (`AsyncOpenAI` for NVIDIA NIM and `genai.Client` for Google Gemini).
   - `langchain-google-genai` brings in the deprecated `google-generativeai` SDK as a transitive dependency, causing package bloat and potential version collisions with the official new `google-genai` SDK.
   - **Recommendation**: Remove `langchain-nvidia-ai-endpoints` and `langchain-google-genai` from `requirements.txt`. Configure NeMo Guardrails to use direct OpenAI engine configurations for NVIDIA NIM and Gemini.
2. **Embedding Dimension Vector Store Incompatibility**:
   - `GEMINI_EMBEDDING_MODEL = "models/text-embedding-004"` produces 768-dimensional vectors, while `NVIDIA_EMBEDDING_MODEL = "nvidia/nv-embedqa-e5-v5"` produces 1024-dimensional vectors matching the Pinecone index dimension (1024-dim).
   - If Gemini is ever routed for dense vector embedding generation in Pinecone, queries will fail with dimension mismatch errors. Gemini embedding model should be set to `text-embedding-004` with explicit output dimension truncation or note that embedding fallback requires dimension alignment.

---

## 5. Verification & Remediation Guidance

| Component | Target Verification Command / Action |
|---|---|
| **Streaming Pipeline** | Test `async for chunk in router.generate_stream(...)` against SSE response endpoint to confirm no `TypeError` is raised. |
| **Circuit Breaker** | Simulate 5 consecutive HTTP 500 errors from NVIDIA NIM provider and verify state transitions: `CLOSED` -> `OPEN` -> `HALF_OPEN` -> `CLOSED`. |
| **NVIDIA Rerank API** | Inspect payload format sent to NVIDIA NIM `/v1/ranking` verifying `{"text": ...}` object format. |
| **NeMo Guardrails** | Run `generate_with_guardrails` with off-topic and jailbreak inputs to confirm `GuardrailsResult.blocked` is True and `response` is valid `str | None`. |
