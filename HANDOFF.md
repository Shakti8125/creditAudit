# Handoff — UI↔backend wiring + RAG Performance feature

> **Read this first in any new session working on this repo.** It is the single source of truth for the
> work done on branch `claude/eager-mendel-u8o13f` (Sept 2026). Supporting design docs are archived in
> [`docs/handoff/`](docs/handoff/).

| | |
|---|---|
| **Branch / PR** | `claude/eager-mendel-u8o13f` → [Shakti8125/creditAudit#2](https://github.com/Shakti8125/creditAudit/pull/2) (pushing to the branch updates the PR) |
| **Base** | `main` @ `681d5ab` — `main` has not moved since, so the branch merges cleanly |
| **Size** | 97 files, +18.9k / −1.6k lines, 11 commits (list in §11) |
| **Status** | Feature-complete and tested offline. **Not yet verified against live LLM providers, Pinecone or Postgres** (see §8). |
| **Next action** | Get PR #2 green → merge to `main` → deploy runs the new Alembic migration → live smoke test (§7) |

The original request had two parts:
1. *"Some UI components do not work as they don't have any backend support. Remove them if making them work needs significant backend effort, otherwise add the backend."*
2. *"I want a page or functionality where I can check the performance of the RAG."*

---

## 1. Pick-up checklist for a new session

```bash
git fetch origin && git checkout claude/eager-mendel-u8o13f
# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
DATABASE_URL=sqlite+aiosqlite:///./ci_test.db python -m pytest -q          # expect 280 passed
python -m ruff check app --select E9,F63,F7,F82                           # expect "All checks passed!"
# frontend
cd ../frontend && npm ci && npm run lint && npm run build                  # both clean, no size warning
```

Project rules live in [`.agents/AGENTS.md`](.agents/AGENTS.md) (async-first, tenant_id on every query,
**no raw entity names to any LLM/embedding/rerank provider**, egress validator before every provider call).

---

## 2. Part 1 — UI components vs backend

An audit classified every interactive element in `frontend/src` (full audit + frozen contract:
[`docs/handoff/ui-backend-gap-audit.md`](docs/handoff/ui-backend-gap-audit.md)). Rule applied: **wire it if the
backend work is small and reuses existing tables; remove it otherwise.** No migration was needed for this part.

### 2.1 Wired (now real, end to end)

| Feature | Backend | Frontend |
|---|---|---|
| Notifications + unread dot | `api/documents.py` creates a `Notification` on every upload (PASS/WARNING/BREACH, or INFO on failure) | `App.tsx` `reload()`, `TopNav` dot only when unread > 0, `NotificationsDrawer` reports count |
| "AI Reviews" KPI | `GET /dashboard/metrics` → `ai_reviews` (assistant messages in tenant) | `OverviewView`, `adapters.toDashboardMetrics` |
| AI Analyst scoped to the model | `POST /query` accepts `model_version_id`; retrieves over the version's latest READY document | `sse.ts`, `WorkspaceView` (keyed by model+version) |
| Chat history + "New conversation" | `GET /query/sessions`, `GET /query/sessions/{id}/messages` (owner-only) | `WorkspaceView` hydrates latest session |
| Privacy Inspector redaction log | `GET /privacy/redactions` now owner-checked | `PrivacyInspectorDrawer` fetches by chat session |
| Settings actually take effect | `PUT /settings` re-scores every model's current version (`policy_checker.compute_model_status` shared helper) | `SettingsView onSaved → reload()`; Gini copy corrected |
| Metric cards follow backend policy | — (uses stored `gap_analysis.results`) | `WorkspaceView` cards/thresholds from `PolicyResult[]`; "Not reported" when missing |
| Model compare correctness | `POST /models/compare`: baseline card shows baseline values; Gini/KS normalised | `CompareModelsView` |
| LLM gap analysis persisted | `POST /gap-analysis` saves to `documents.metadata_json.llm_gap_analysis` | Gap tab shows it with Run / Re-run |
| Citation navigation | — | Sources open the document or the focused Regulatory Library standard |
| Global search | `GET /search` also matches standard code/description and document filenames | `TopNav` results clickable |
| Profile edit | `PATCH /users/me` (full_name, title, division) | `ProfileModal` edit + save |
| Export options | `GET /models/{id}/export-data?include_citations&include_audit_trail` | `ExportReportModal` |
| Model versions | `POST /models/{id}/versions` (409 on duplicate; new version = current, status reset to PENDING) | `ModelLineageModal` "New version" |
| Honest status / "last analyzed" | `ModelSummary.last_analyzed_at` | `PENDING` status for unanalysed models |
| Robust New Audit / uploads | — | Orphaned-model fix, form reset, reload after upload or failure, document Delete button, explicit Compare button in `DocumentCompareView` |

### 2.2 Removed (no backend support; building it would be significant or low-value)

| Removed | Why |
|---|---|
| Storage quota widget (`SideNav`) | Hardcoded; needs file-size tracking + quotas |
| Synthetic ROC curve (`lib/roc.ts` deleted) | Was reconstructed from AUC alone; a real ROC needs score/label data documents don't contain |
| Masking toggles (`auto_mask_*`, `strict_zero_trust`) | Backend ignored them; honouring them would weaken zero-trust. Replaced by a read-only "always enforced" panel. DB columns kept. |
| Min-observation-window setting + compare "Data Configuration" | Never enforced / no per-model extraction |
| PDF/DOCX export buttons, no-op JSON button | No rendering service; JSON download kept |
| Fixed "Recommended Actions" chips (+ backend `suggestedActions` SSE event) | Same 3 hardcoded strings every time |
| "Active Framework" badge, Security-clearance row, "Zero PII leaks", "• Production" suffix | Hardcoded claims |
| Duplicate `login/register/refreshToken` in `lib/api.ts` | Dead code (auth lives in `useAuth`/`http.ts`) |

---

## 3. Part 2 — RAG Performance feature

New nav item **"RAG Performance"** (lazy-loaded page). Full design with the frozen API contract:
[`docs/handoff/rag-performance-design.md`](docs/handoff/rag-performance-design.md) (§2 = contract).
**Source of truth for the contract is now the code:** `backend/app/schemas/rag_eval.py` ⇔
`frontend/src/lib/ragTypes.ts` (must stay field-for-field identical; a review script found 0 mismatches).

### 3.1 How it works

```
ONLINE (every real call)                                OFFLINE (golden dataset)
/query (SSE) ──┐                                        rag_eval_cases (22 default CBUAE cases + tenant CRUD)
/regulatory/search ─┤ RagTraceRecorder                        │  POST /rag/eval/runs  (modes × top_k × generation?)
               │  per-stage timers, retrieval diagnostics      ▼  BackgroundTask → runner (own DB session, heartbeat)
               │  LLMRouter.call_log, masked query only     per case: mask → egress → HybridRetriever(mode)
               ▼                                              → IR metrics → [generate → LLM judge | deterministic]
          rag_traces ◄── rag_feedback (👍/👎 per user)          ▼
               │                                         rag_eval_runs (+aggregates) / rag_eval_results
               ▼
  GET /rag/telemetry/dashboard, /rag/traces[/id]          GET /rag/eval/runs[/id][/results]
                     └──────────── RagPerformanceView (frontend) ────────────┘
```

- **Telemetry**: per-stage latency (masking, dense, bm25, fusion, rerank, retrieval, generation, TTFT, total),
  candidate counts, normalised top scores per scorer, provider/model + failover, rerank fallback, guardrail
  blocks, estimated tokens (chars/4 — providers don't return usage), status ok/error/blocked/cancelled.
  **Only masked query text is ever stored.** Telemetry failures never break a request.
- **Feedback**: 👍/👎 (+ tags, comment — comment is masked) on AI Analyst answers (SSE `trace` event) and
  Regulatory Q&A answers (`trace_id` in JSON). One vote per (trace, user).
- **Offline eval**: retrieval modes `dense | bm25 | hybrid | hybrid_rerank` (production = `hybrid_rerank`),
  metrics Hit@k, Recall@k, Precision@k, MRR, nDCG@k (target-coverage gain), plus faithfulness / answer
  relevance via LLM judge (falls back to deterministic token-overlap when the LLM is unavailable).
  One run per mode, grouped; one active run per tenant (409); ≤200 cases; stale runs auto-failed after 10 min.

### 3.2 Endpoints (all `/rag/*`, Bearer auth, tenant-scoped, cross-tenant ids → 404)

| Method & path | Purpose |
|---|---|
| `GET /rag/telemetry/dashboard?window=24h\|7d\|30d\|90d&endpoint=all\|query\|regulatory_search` | KPIs, per-stage p50/p95, timeseries, by-endpoint, feedback |
| `GET /rag/traces` (`window, endpoint, status, mine, limit, offset`) / `GET /rag/traces/{id}` | Trace list / detail |
| `POST /rag/feedback` / `DELETE /rag/feedback/{trace_id}` | Upsert / remove my vote |
| `GET/POST /rag/eval/cases`, `PATCH/DELETE /rag/eval/cases/{id}`, `POST /rag/eval/cases/restore-defaults` | Golden dataset (GET lazily seeds 22 defaults) |
| `POST /rag/eval/runs` (202), `GET /rag/eval/runs[/{id}[/results]]`, `POST /rag/eval/runs/{id}/cancel`, `DELETE /rag/eval/runs/{id}` | Eval runs |

Changed existing endpoints: `POST /query` SSE now emits `{"type":"trace","content":"<uuid>"}` right after
`session_id`; `POST /regulatory/search` response gains `trace_id`.

### 3.3 Database — migration `d4e5f6a7b8c9` (down_revision `c7d8e9f0a1b2`)

New tables: `rag_traces`, `rag_feedback`, `rag_eval_cases`, `rag_eval_runs`, `rag_eval_results`
(models in `backend/app/models/rag_eval.py`). Verified upgrade + downgrade on SQLite and `alembic check`
shows no drift. **Not yet run on Postgres.**

### 3.4 Key files

- Backend: `app/api/rag_eval.py`, `app/services/evaluation/{metrics,dashboard,telemetry,prompts,judge,default_dataset,runner}.py`,
  instrumentation in `app/api/query.py` + `app/api/regulatory.py`, `app/services/retrieval/hybrid_retriever.py`
  (per-stage timing, `mode` ablation, diagnostics), `app/services/llm/router.py` (`call_log`).
- Frontend: `src/components/RagPerformanceView.tsx`, `src/components/rag/*` (inline-SVG charts, no chart lib),
  `src/lib/{ragApi,ragTypes,ragFormat}.ts`, `FeedbackControl` in `WorkspaceView` + `RegulatoryLibraryView`.

---

## 4. Bugs fixed along the way (security / privacy / reliability)

| Severity | Fix | Where |
|---|---|---|
| **Privacy (critical)** | `/query` and `/regulatory/search` sent the **raw** question to NVIDIA/Gemini embedding + rerank before masking. Now mask + egress-validate **before** retrieval. | `api/query.py`, `api/regulatory.py` |
| **Security** | `GET /privacy/redactions` and `POST /privacy/mask` returned the raw→token map for **any** session UUID. Now owner-only (404). Chat-session reuse now requires the same user. | `api/privacy.py`, `api/query.py` |
| **High** | Questions mentioning CBUAE / "CBUAE MMG" / ECL / SICR / UAE / "Board Risk Committee" were masked as entities while the retrieved corpus contained them verbatim → egress block → 500 on every such question. Added `PROTECTED_DOMAIN_TERMS`; real bank/org/person names still masked. | `services/privacy/ner_masker.py`, `tests/test_privacy_domain_terms.py` |
| Medium | Raw 500s → egress block **422**, provider outage **503**, privacy-safe messages (`app/api/errors.py`) on `/query`, `/regulatory/search`, `/compare`, `/gap-analysis` | |
| Medium | Upstream provider payloads (e.g. Google `API_KEY_INVALID` JSON) no longer echoed to clients (document upload, SSE error event) | `api/documents.py`, `utils/streaming.py` |
| Medium | Router promoted Gemini to primary as soon as NVIDIA had any latency sample (empty history read as 0 ms) | `services/llm/router.py` |
| Medium | Router called providers with missing/placeholder keys; now skipped (`is_configured`), all-failed → `AllProvidersUnavailableError` | `router.py`, `base_provider.py`, providers |
| Medium | NVIDIA retry crashed with `AttributeError` on connection/timeouts (no `status_code`) — now retried with backoff | `nvidia_provider.py` |
| Medium | Gemini rerank scored every failed passage 0.0 so the reranker fallback never fired | `gemini_provider.py` |
| Low | Concurrent first-time eval-case seeding → IntegrityError 500 | `evaluation/default_dataset.py` |
| Low | nDCG penalised duplicate chunks of an already-covered target (biased against dense/hybrid) | `evaluation/metrics.py` |
| Low (UI) | Gap-tab spinner stuck, stale compare result, chat spinner on empty answer, feedback on errored answers, favicon 404 | frontend |

---

## 5. Configuration

API keys (NVIDIA, Gemini, Pinecone, Upstash Redis, JWT keys) are stored in **Render and GitHub secrets**
per the project owner. Env var names (see `backend/.env.example`, `backend/app/config.py`):
`DATABASE_URL, REDIS_URL, REDIS_TOKEN, NVIDIA_API_KEY, NVIDIA_BASE_URL, GEMINI_API_KEY, PINECONE_API_KEY,
PINECONE_INDEX_NAME, JWT_PRIVATE_KEY, JWT_PUBLIC_KEY, JWT_SECRET_KEY, JWT_ALGORITHM, ALLOWED_ORIGINS, RATE_LIMIT_ENABLED`.

- **New:** `RAG_TELEMETRY_ENABLED` (default `true`) — ops kill switch. When `false`, trace ids are still
  returned but not persisted, so feedback on them 404s.
- **Behaviour change:** a provider whose key is missing or equals the placeholder (`nvapi-placeholder`,
  `gemini-placeholder`) is **skipped**. If neither is configured, LLM endpoints return **503**. Make sure both
  keys are set in every deployed environment.
- **JWT:** set `JWT_PRIVATE_KEY`/`JWT_PUBLIC_KEY` explicitly — without them `app/utils/security.py` generates
  random keys per process start, invalidating tokens on every restart / across workers.

---

## 6. Hosting note (confirm before deploying)

The repo's workflows deploy the backend to **AWS ECS Fargate** (`.github/workflows/deploy-production.yml`,
which runs `alembic upgrade head` as a one-off task) and the frontend to **Vercel**. The owner has **stopped
the AWS servers** and mentions keys living in **Render**. There is no Render config in the repo. A new session
should confirm which backend host is live and, if it is Render, make sure `alembic upgrade head` runs there
(e.g. as a pre-deploy command), because the RAG feature needs migration `d4e5f6a7b8c9`.

---

## 7. Deploy & live verification checklist (not done yet)

1. PR [Shakti8125/creditAudit#2](https://github.com/Shakti8125/creditAudit/pull/2) (`claude/eager-mendel-u8o13f` → `main`): CI (`.github/workflows/ci.yml`) must be green before merging.
2. Deploy; confirm `alembic upgrade head` applied `d4e5f6a7b8c9` (five `rag_*` tables exist).
3. Seed the regulatory catalog if empty: `cd backend && python -m scripts.seed_regulatory_standards`.
4. Make sure the regulatory corpus is indexed in Pinecone (`python -m scripts.index_regulatory_corpus`) —
   dense/hybrid eval and regulatory Q&A quality depend on it.
5. Smoke test with live keys:
   - Regulatory Library → ask "Summarise the PD validation requirements in the CBUAE MMG" → an answer
     (previously a 500), 👍 it, then RAG Performance → dashboard shows the trace and the vote.
   - AI Analyst on a model with an uploaded document → answer + citations + feedback control.
   - RAG Performance → Evaluation → run **all four modes**, top-k 5, generation **on**. Record the baseline
     (Hit@5 / MRR / nDCG / faithfulness per mode). This is the first real measurement of RAG quality, and also
     measures the effect of the masked-retrieval privacy fix.
6. Check logs for `EgressViolationError` / `AllProvidersUnavailableError` spikes.

---

## 8. Verification done (and not done)

- **Automated:** backend **280 passed** (134 existing + 146 new), ruff clean; frontend `tsc` + `vite build` clean
  (code-split: app 166 kB, vendor 350 kB, RAG page 122 kB).
- **End-to-end QA (offline, no provider keys)**, driven with Playwright on SQLite + uvicorn + Vite:
  register/login, every nav page and drawer/modal, profile/settings persistence, model + new version + export
  + search, RAG dashboard/traces/feedback, eval dataset CRUD + restore defaults, two bm25 eval runs + comparison,
  concurrent seeding, 375 px layout (no horizontal scroll). All passed except flows needing live providers.
- **Not verified:** live NVIDIA/Gemini/Pinecone calls; dense/hybrid/rerank eval numbers; Postgres (migration and
  queries); Upstash rate limiting with the new endpoints.
- Offline BM25-only eval saturates (Hit@5 1.00, MRR 0.98) because the BM25 fallback corpus
  (`CBUAE_REGULATORY_CORPUS` in `hybrid_retriever.py`) has only 10 sections. Meaningful numbers need live keys
  (step 7.5).

---

## 9. Known issues / backlog (all verified in code; none introduced by this branch unless noted)

| # | Issue | Pointer | Suggested fix |
|---|---|---|---|
| 1 | Upload is all-or-nothing: if embedding fails the document goes to ERROR and already-extracted metrics are discarded | `api/documents.py` upload pipeline | Persist metrics/policy results before embedding; mark embedding failure separately |
| 2 | Deleting a model's last document leaves the version's metrics / gap analysis / status | `api/documents.py` delete | Recompute or clear on delete |
| 3 | After "New version", documents on older versions are hidden in the Documents tab (search hits/citations to them select another doc) | `WorkspaceView.tsx` Documents tab | Add a version filter / show all versions |
| 4 | Traces are visible tenant-wide (masked text) while chat sessions are private (by contract; `mine` filter exists) | `api/rag_eval.py` | Decide policy; optionally restrict to own traces for non-admins |
| 5 | BM25 returns zero-score corpus items, so `bm25_count` is always 10 and the reranker scores irrelevant passages | `services/retrieval/bm25.py` | Filter `score > 0`; measure with the eval before/after |
| 6 | Citation identity differs between BM25 (`doc-{uuid}`/`chunk-{i}`) and dense (filename/header) for document chunks | `hybrid_retriever.py`, `api/documents.py` | Unify source/section naming |
| 7 | Token counts are estimates (chars/4) | `evaluation/telemetry.py` | Capture provider `usage` (OpenAI `stream_options.include_usage`, Gemini `usage_metadata`) |
| 8 | One-active-eval-run (409) check is check-then-insert (race) | `api/rag_eval.py` | Partial unique index or advisory lock |
| 9 | >200 `case_ids` returns 422 instead of the contract's 400 | `schemas/rag_eval.py` | Cosmetic |
| 10 | NVIDIA rerank transport errors are not retried | `nvidia_provider.py` rerank | Reuse the retry wrapper |
| 11 | `/query` doesn't check `document_id` belongs to `model_version_id` (tenant-safe) | `api/query.py _resolve_query_scope` | Validate the pairing |
| 12 | In-memory entity registry (`registry_store`) is per-process: redaction log empty under multiple workers/restarts | `services/privacy/registry_store.py` | By design (AGENTS.md forbids persisting it); document for ops |
| 13 | `Document.raw_markdown` stores unmasked text | `models/document.py` | Consider encrypting or dropping after processing |
| 14 | `deployment_steps.md` still references the removed ROC chart | `deployment_steps.md` ~l.999 | Update the doc |

---

## 10. Where things are (quick map)

```
backend/app/api/        rag_eval.py (new), errors.py (new), query.py, regulatory.py, system.py, models.py,
                        documents.py, privacy.py, gap_analysis.py, compare.py
backend/app/services/   evaluation/* (new), retrieval/{hybrid_retriever,reranker}.py, llm/{router,nvidia_provider,
                        gemini_provider,base_provider}.py, privacy/ner_masker.py, analytics/policy_checker.py
backend/app/models/     rag_eval.py (new)          backend/app/schemas/  rag_eval.py (new), query.py, system.py, models.py
backend/alembic/versions/d4e5f6a7b8c9_add_rag_telemetry_and_eval_tables.py (new)
backend/tests/          test_ui_backend_wiring.py, test_rag_*.py, test_llm_router_call_log.py, test_privacy_domain_terms.py,
                        test_gemini_provider.py, test_streaming.py (all new) + updates to existing router/guardrail tests
frontend/src/           components/rag/* + RagPerformanceView.tsx (new), lib/{ragApi,ragTypes,ragFormat}.ts (new),
                        App.tsx, types.ts, lib/{api,sse,adapters}.ts, most components; lib/roc.ts deleted
docs/handoff/           ui-backend-gap-audit.md, rag-performance-design.md
```

---

## 11. Commits (oldest → newest)

| SHA | Summary |
|---|---|
| `d036aaf` | feat(api): back previously mock UI features with real endpoints |
| `5adc280` | feat(frontend): wire UI to new endpoints and remove non-functional components |
| `dc69fe5` | fix(frontend): review fixes for UI wiring |
| `878fd45` / `a62c04f` | feat(rag): RAG telemetry, feedback and offline evaluation backend (+ merge resolving `query.py`) |
| `ccfba9c` / `430ba05` | feat(rag): RAG Performance page and answer feedback in the UI (+ merge, vendor chunk split) |
| `a651535` | fix(rag): tolerate concurrent default eval-case seeding |
| `7db3072` | fix(rag): nDCG no longer penalises duplicate chunks of a covered target |
| `4d8e1f9` | fix(privacy): stop masking public regulatory vocabulary as entities |
| `57ed809` | fix: handled errors for provider outages and egress blocks; routing fixes |
| *(this commit)* | docs: handoff document + archived design docs |
