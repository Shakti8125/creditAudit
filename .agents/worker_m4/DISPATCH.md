## 2026-08-28T13:50:56Z

You are a specialist Worker for ModelAudit AI Milestone 4: LLM Providers, Circuit Breaker & Routing.

# Instructions & Context
- You MUST read ORIGINAL_REQUEST.md: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md`
- You MUST read the Master Bug Report: `c:\Users\Shakti\Documents\CreditAudit- AI\backend_code_audit_report.md`
- Project Identity & Rules: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md`
- Domain Skills to load if needed: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\skills\p4-llm-routing\SKILL.md`
- Your working directory for agent metadata is: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m4`

# Exclusive File Ownership
You exclusively own and may edit:
- `backend/app/services/llm/router.py`
- `backend/app/services/llm/circuit_breaker.py`
- `backend/app/services/llm/nvidia_provider.py`
- `backend/app/services/llm/gemini_provider.py`
- `backend/app/services/llm/base_provider.py`
- `backend/app/services/llm/__init__.py`

DO NOT edit files outside this list.

# Assigned Issues to Resolve
1. LLM-01 (Critical): In `router.py`, implement `generate_stream` as a direct async generator with `yield chunk` iterating over `provider.generate_stream(...)` rather than returning an inner coroutine/generator.
2. LLM-02 (High): In `router.py`, implement automatic fallback/failover to the secondary available provider in `generate` and `generate_stream` if the primary provider fails.
3. LLM-03 (Critical): In `circuit_breaker.py`, provide a dedicated `call_stream` async generator wrapper so async generators are not passed to `await func()`.
4. LLM-04 (High): In `circuit_breaker.py`, guard state transitions (`CLOSED` -> `OPEN` -> `HALF_OPEN` -> `CLOSED`) with `asyncio.Lock()` to prevent race conditions during concurrent probes.
5. LLM-05 (Critical): In `nvidia_provider.py`, fix the NVIDIA NIM Reranking API call: use relative URL `"ranking"` (avoiding stripping `/v1` from base url), and format payload with `query: {"text": query}` and `passages: [{"text": p} for p in passages]`.
6. LLM-06 (High): In `nvidia_provider.py` (and any HTTP clients), manage `httpx.AsyncClient` lifecycle and provide `aclose()`.
7. LLM-07 (Medium): In `base_provider.py`, add default parameter values (`temperature: float = 0.7`, `max_tokens: int = 1024`) to abstract method signatures and match them in concrete implementations.
8. Re-export public LLM classes in `services/llm/__init__.py`.
