# PR-00 verification runbook (local)

Rewritten 2026-10-04 (task X-02). The original runbook inspected AWS (ECS, CloudWatch, CloudTrail) and ran a one-off ECS probe task. **The AWS account is gone (D12), so those steps are void.** What remains of PR-00 is the keyed probe, run **on the owner's machine** with the local `.env`. Record the results in [README §5](README.md#5-verification-log).

An agent sandbox cannot run it: its egress policy blocks `integrate.api.nvidia.com`, `ai.api.nvidia.com` and `api.pinecone.io`, and the keys are not there.

---

## How to run it (about five minutes)

1. **Env file.** `cp backend/.env.example backend/.env`, then fill in:
   - `NVIDIA_API_KEY` (needed), `GEMINI_API_KEY` (for the backup checks);
   - `PINECONE_API_KEY` and `PINECONE_INDEX_NAME` (for the index and dimension check);
   - `REDIS_URL` and `REDIS_TOKEN` only if you use Upstash (the **REST** URL, `https://...upstash.io`); leave them empty otherwise.

   `.env` is git-ignored. Never commit it or paste it anywhere.
2. **Minimal install.** The probe needs only a few packages, not the full `requirements.txt` (Docling and spaCy are heavy):
   ```bash
   cd backend
   python3.12 -m venv .venv && . .venv/bin/activate
   pip install httpx pydantic pydantic-settings pinecone upstash-redis
   ```
3. **Run it** from `backend/`:
   ```bash
   python -m scripts.diag.pr00_probe                              # everything
   python -m scripts.diag.pr00_probe --only nvidia,gemini,pinecone  # skip Redis
   ```
   Sections are `nvidia`, `gemini`, `pinecone` and `redis`. A section without its key prints `*_skipped`; one failing section never stops the others.
4. **Record it.** Paste the `PR00 {...}` lines into README §5 and tick the decisions below. The lines hold names, HTTP status codes, `finish_reason`, lengths, token counts, dimensions and booleans only, so they are safe to paste.

## What it calls (synthetic text only)

| Provider | Calls | Purpose |
|---|---|---|
| NVIDIA | `GET /v1/models` (1) | Are the IDs listed? A listing does not prove a model works. |
| NVIDIA | rerank, old and new model (2) | QA-006: the old endpoint is deprecated; the successor should return 200. |
| NVIDIA | chat, both generation models, `max_tokens=64` (2) | Liveness of the primary and of the 404 fallback. |
| NVIDIA | chat, primary model, 7 structured-output variants (7) | QA-005: the request as deployed (top-level `guided_json`, no thinking flag, `temperature=0.7`, `max_tokens=1024`), then top-level `guided_json`, `nvext.guided_json` and `response_format` (json_schema), each with thinking on and off. |
| NVIDIA | embeddings, default and `dimensions=1024` (2) | The native dimension of `nemotron-3-embed-1b`, and whether a 1024 truncation is honoured. |
| Gemini | `GET models/<id>` (9) and the model list | Status of the retired, current and candidate IDs (2.0-flash, text-embedding-004, 2.5-flash, 3.5-flash, 3.6-flash, 3.8-flash, flash-latest, embedding-001, embedding-2). |
| Gemini | `generateContent`, chain 3.6 → 3.5 → `flash-latest` (3) | Free-tier entitlement (D11) and which model actually serves the alias. |
| Gemini | structured output on 3.6-flash (1-2) | `responseJsonSchema`, then `responseSchema` if the first is rejected (PR-02 input). |
| Pinecone | `list_indexes`, `describe_index`, `describe_index_stats` | Index dimension, metric, spec and state; namespaces grouped by prefix (tenant and document IDs are never printed); whether `cbuae-manuals` is present or empty (QA-001, NEW-07). |
| Upstash | `PING`, `SCRIPT LOAD token_bucket.lua` | Whether the rate limiter's Redis works. `SCRIPT LOAD` is idempotent; the app does the same at startup. |

That is 14 NVIDIA calls and at most 5 Gemini generation calls on the free tiers (D11), plus about 10 Gemini metadata reads. Nothing is written to Postgres or Pinecone. The Gemini key travels in a header, never in a URL, and every configured secret is scrubbed from the output. Tests: `backend/tests/test_pr00_probe.py`.

## What each result decides

| Result | Decides |
|---|---|
| `nvidia_rerank`: new model 200, old 404 or 410 | PR-01 item 1 (reranker successor). |
| `nvidia_structured`: which variant gives `finish_reason=stop` and `schema_ok=true`, with and without thinking | PR-02 item 1 (`nvext.guided_json` or `response_format`, thinking off). |
| `nvidia_embed.dimension` against `pinecone_index.dimension` (`embed_vs_index.match`) | Whether the embedding call must pin `dimensions` (CorpusPlan §8) before any ingest. |
| `gemini_model` and `gemini_generate` statuses and `model_version` | PR-01 default model and the PR-01b chain; free-tier entitlement (D11). |
| `gemini_structured`: which schema field works | PR-02, Gemini side. |
| `pinecone_stats.namespace_count` and `by_prefix` | NEW-07 (namespace cap). The plan tier is not exposed by the API; read it in the Pinecone console. |
| `config` and `redis` lines | Whether the local rate-limiter configuration is sane (PR-06-lite). Rate limiting is off in the local demo anyway (`RATE_LIMIT_ENABLED=false`). |

**Void under D12:** the ECS environment check, the CloudWatch Logs Insights queries, the CloudTrail `RunTask` history, NEW-06 (shared task definition) and the QA-007 production-config question. The first runbook's helper (`pr00_aws.py`) was removed by X-02.
