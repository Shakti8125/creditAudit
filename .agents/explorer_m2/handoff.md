# Handoff Report — Explorer M2 (LLM Providers & NeMo Guardrails)

## 1. Observation
During the static audit of the LLM Providers and NeMo Guardrails services, the following specific code patterns were directly observed:
- `backend/app/services/llm/router.py:122-146`: `generate_stream` is defined with `async def` and executes `return _yield_and_record()`, returning a coroutine object wrapping an async generator. Callers in `app/api/query.py:56` attempt `stream = await llm_router.generate_stream(prompt, system_prompt)` while callers in standard streaming endpoints expect direct async iteration. In addition, `await cb.call(func, ...)` awaits an async generator function, causing a `TypeError`.
- `backend/app/services/llm/nvidia_provider.py:137-143`: `payload` in `rerank` passes raw string `query` and list of strings `passages` instead of `{"text": ...}` objects. `self.httpx_client.post("/ranking", json=payload)` strips `/v1` from `https://integrate.api.nvidia.com/v1` due to leading slash in httpx URL resolution.
- `backend/app/services/guardrails/guardrails_service.py:47-60, 101`: `await self.rails.generate_async(messages=messages)` returns a dict `{"role": "assistant", "content": "..."}`, but code compares `if response == "string"` directly and assigns `response` to `GuardrailsResult.response` typed as `str | None`.
- `backend/app/services/guardrails/guardrails_service.py:34, 47-54`: Parameters `context` and `retrieved_contexts` are accepted by `generate_with_guardrails` but never passed into `self.rails.generate_async()`, leaving custom actions in `actions.py` with empty context.
- `backend/app/services/guardrails/rails.co:43-48`: `define flow check hallucination against context` references `bot refuse to respond`, which is never defined in `rails.co`.
- `backend/app/api/query.py:22`, `compare.py:63`, `gap_analysis.py:54`, `regulatory.py:20`: Instantiates fresh `LLMRouter()` on each HTTP request, resetting latency history and circuit breaker state.
- `backend/app/services/guardrails/config.yml:1-14`: Two models both configured with `type: main`, and `colang_version: "2.x"` is omitted.

## 2. Logic Chain
1. **Streaming Failure Chain**: `generate_stream` in `nvidia_provider.py` and `gemini_provider.py` is an async generator -> `cb.call` awaits it -> Python raises `TypeError: object async_generator can't be used in 'await' expression`. In `router.py`, `generate_stream` returns an async generator from an `async def` function -> caller gets a Coroutine instead of an AsyncIterator -> `TypeError: 'coroutine' object is not an async iterable`.
2. **NVIDIA Rerank Failure Chain**: NVIDIA NIM `/v1/ranking` endpoint strictly requires `{"query": {"text": ...}, "passages": [{"text": ...}]}` -> passing raw strings causes HTTP 422. Calling `client.post("/ranking")` against `base_url="https://integrate.api.nvidia.com/v1"` strips `/v1` per RFC 3986 -> hits `/ranking` and returns HTTP 404.
3. **Guardrails Failure Chain**: NeMo Guardrails `generate_async(messages=...)` returns a dictionary -> string equality checks fail -> blocked responses are never identified -> dict is passed to Pydantic `str` field causing validation failure. Omitting `context` parameter from `generate_async` deprives `check_hallucination_action` of `retrieved_contexts`, causing hallucination detection to return `0.0` always.

## 3. Caveats
- Strictly read-only audit: no code was executed and no packages were installed.
- Dynamic behavior of NeMo Guardrails Colang 2.0 runtime depends on `nemoguardrails` version installed.

## 4. Conclusion
The LLM Provider and NeMo Guardrails subsystem has 16 identified defects: 6 Critical, 5 High, 4 Medium, and 1 Low. The most severe issues affect streaming execution (`generate_stream`), NVIDIA NIM reranking payload/URL resolution, NeMo Guardrails response dictionary parsing, and state loss from router re-instantiation. Detailed per-file findings and exact fixes are documented in `report.md`.

## 5. Verification Method
1. Inspect `report.md` for exact line numbers and code fix snippets.
2. Review `backend/app/services/llm/router.py` against Python async generator semantics.
3. Verify NVIDIA NIM `/v1/ranking` API specifications in official NVIDIA documentation.
4. Verify `LLMRails.generate_async` return types in NeMo Guardrails documentation.
