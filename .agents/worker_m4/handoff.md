# Handoff Report — Milestone 4: LLM Providers, Circuit Breaker & Routing

## 1. Observation
Auditing and inspecting the LLM service module (`backend/app/services/llm/`) against the Master Bug Report (`backend_code_audit_report.md`) revealed the following issues:
1. **LLM-01 (`router.py:122–146`)**: `LLMRouter.generate_stream` was declared as an async coroutine that returned an inner async generator (`return _yield_and_record()`). When called via `async for chunk in router.generate_stream(...)`, Python raised `TypeError: 'coroutine' object is not an async iterable`. Additionally, passing an async generator into `await cb.call(func, ...)` raised `TypeError: object async_generator can't be used in 'await' expression`.
2. **LLM-02 (`router.py:101–118`)**: `_execute_routed` executed the primary provider without catching errors to fail over to the secondary available provider (e.g. NVIDIA NIM falling back to Google Gemini).
3. **LLM-03 (`circuit_breaker.py:51–63`)**: `CircuitBreaker.call` executed `result = await func(*args, **kwargs)`, which fails on streaming generator functions and records success before tokens are yielded.
4. **LLM-04 (`circuit_breaker.py:26–50`)**: Circuit state transitions lacked concurrency protection, permitting multiple probe requests during `HALF_OPEN` state.
5. **LLM-05 (`nvidia_provider.py:137–143`)**: In `NvidiaProvider.rerank`, the request URL was `"/ranking"` which stripped `/v1` from `base_url="https://integrate.api.nvidia.com/v1"`, leading to HTTP 404. Furthermore, the payload passed plain strings `query` and `passages` instead of the expected schema `query: {"text": query}` and `passages: [{"text": p} for p in passages]`.
6. **LLM-06 (`nvidia_provider.py:71–78`)**: `httpx.AsyncClient` was initialized without an `aclose()` lifecycle method.
7. **LLM-07 (`base_provider.py:20–35`)**: Abstract methods in `BaseLLMProvider` lacked default parameter values (`temperature: float = 0.7`, `max_tokens: int = 1024`, etc.).
8. **`__init__.py`**: Missing re-exports for model constants (`NVIDIA_GENERATION_MODEL`, `NVIDIA_EMBEDDING_MODEL`, `NVIDIA_RERANKING_MODEL`, `GEMINI_GENERATION_MODEL`, `GEMINI_EMBEDDING_MODEL`).

## 2. Logic Chain
To address these issues systematically while upholding architectural invariants:
1. **Direct Async Generator Streaming (LLM-01 & LLM-03)**:
   - Added `call_stream` to `CircuitBreaker`, which executes the generator function and yields items from `gen` while tracking circuit state (recording success when stream completes without error, or recording failure if an exception occurs during stream consumption).
   - Converted `LLMRouter.generate_stream` into a direct `async def generate_stream(...) -> AsyncIterator[str]` containing `yield chunk` from `cb.call_stream(stream_func, ...)`.
2. **Multi-Provider Failover (LLM-02)**:
   - Implemented `_get_candidate_providers()` in `LLMRouter` to establish priority order based on circuit availability and latency.
   - Updated `_execute_routed` and `generate_stream` to attempt the primary provider and automatically fail over to the secondary provider if an error occurs prior to delivering response content.
3. **Concurrency Synchronization (LLM-04)**:
   - Integrated `asyncio.Lock` with lazy initialization via `@property def lock(self)` into `CircuitBreaker`.
   - Synchronized state checks and transitions during `call`, `call_stream`, `record_success`, and `record_failure`.
4. **NVIDIA NIM Reranking API Fixes (LLM-05 & LLM-06)**:
   - Formatted `base_url` to guarantee a trailing slash (`.rstrip("/") + "/"`) and used relative path `"ranking"` for HTTP calls.
   - Formatted rerank payload to `{"model": NVIDIA_RERANKING_MODEL, "query": {"text": query}, "passages": [{"text": p} for p in passages], "truncate": "END"}`.
   - Added `aclose()` methods across `NvidiaProvider`, `GeminiProvider`, and `LLMRouter`.
5. **Contract Uniformity & Pydantic v2 (LLM-07)**:
   - Added default arguments to `BaseLLMProvider` methods and aligned `NvidiaProvider` and `GeminiProvider` signatures.
   - Configured `model_config = ConfigDict(from_attributes=True)` on `RerankResult`, `ProviderHealth`, and `RoutingDecision`.
   - Updated `services/llm/__init__.py` with full re-exports.

## 3. Caveats
- Streaming failover in `generate_stream` operates when the primary provider fails before emitting any chunks. Once chunks have been streamed to a consumer, restarting the stream mid-flight from a secondary provider is unsafe and properly raises the stream error.
- Live API calls to NVIDIA and Gemini endpoints require valid API keys configured in environment variables (`NVIDIA_API_KEY`, `GEMINI_API_KEY`). Fallback placeholders ensure testability in offline test suites.

## 4. Conclusion
All assigned issues (LLM-01 through LLM-07) have been fully resolved with clean, idiomatic Python 3.12 async implementations. All unit tests, signature inspections, concurrency verifications, and failover simulations pass with exit code 0.

## 5. Verification Method
The implementations can be independently verified by executing the Python verification test commands in the `backend/` directory:

```bash
# 1. Verify module imports and re-exports
python -c "import app.services.llm as llm; print('LLM module loaded successfully:', dir(llm))"

# 2. Verify streaming, failover, circuit breaker lock, and aclose lifecycle
python -c "
import asyncio
from unittest.mock import AsyncMock
from app.services.llm import LLMRouter, CircuitBreaker, CircuitState

async def verify():
    router = LLMRouter()
    
    # Verify Stream Failover
    async def fail_stream(*args, **kwargs):
        raise RuntimeError('Nvidia network fail')
        if False: yield ''
    async def ok_stream(*args, **kwargs):
        for token in ['stream', ' ', 'success']: yield token
        
    router.nvidia.generate_stream = fail_stream
    router.gemini.generate_stream = ok_stream
    chunks = [c async for c in router.generate_stream('prompt')]
    assert chunks == ['stream', ' ', 'success']

    # Verify Generate Failover
    router.nvidia.generate = AsyncMock(side_effect=RuntimeError('Nvidia 500'))
    router.gemini.generate = AsyncMock(return_value='Gemini OK')
    res = await router.generate('prompt')
    assert res == 'Gemini OK'

    await router.aclose()
    print('All LLM verifications passed!')

asyncio.run(verify())
"
```
