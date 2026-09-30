# Live app QA audit - creditAudit / ModelAudit AI (2026-09-30)

Auditor: QA agent (automated, Playwright + curl). Scope: audit only. No tracked code was changed, nothing was committed or pushed.

Screenshots and raw logs are in the agent scratchpad (not in the repo):
`/tmp/claude-0/-home-user-creditAudit/642a91a9-91ae-5385-8c2b-2a30eb725d96/scratchpad/qa/screenshots/` (82 PNGs) and `.../qa/logs/`. File names are cited below as `screenshots/NN-name.png`.

---

## 1. Executive summary

**Verdict on the user's suspicion: CONFIRMED, and it is worse than "one empty index".** In production the regulatory knowledge base is empty at two independent layers (DB catalog and Pinecone `cbuae-manuals` namespace). Regulatory Q&A "works" only because a 10-paragraph hardcoded corpus (`CBUAE_REGULATORY_CORPUS`) is searched with BM25, and every citation in production is `CBUAE-MMG-2022 / Section N` from that array. Several other "regulatory analysis" features are broken for separate reasons (gap analysis 502, reranker failing 100%, doc-scoped chat never sees any regulatory text, multi-turn chat blocked by the privacy egress check).

Top issues, ranked:

| Rank | ID | Severity | Issue (one line) |
|---|---|---|---|
| 1 | QA-001 | Critical | Pinecone namespace `cbuae-manuals` is empty: dense regulatory retrieval returned 0 candidates for every regulatory query traced (22/22 golden cases Hit@5 = 0.00). The indexing script cannot work in the deployed image (`backend/base_documents/` is gitignored and does not exist; script prints "Directory not found" and exits 0) and is not part of any pipeline. |
| 2 | QA-002 | High | `regulatory_standards` table is empty: Regulatory Library catalog shows "No regulatory standards available"; global search never returns a standard; "open standard" navigation from citations/search has nothing to open. Seed script is not part of any pipeline. |
| 3 | QA-003 | High | AI Analyst (document-scoped) never receives any regulatory text, while the UI, Help modal and docs say answers are "grounded in ... the regulatory corpus". Proven: asked for the CBUAE PSI threshold, the answer said it "is not stated in the provided context". |
| 4 | QA-004 | High | Multi-turn chat is broken: the 2nd question in a document-scoped conversation returns HTTP 422 "privacy egress check" (reproduced 2/2: UI and API). Root cause identified: the file name cited in the previous answer is masked as an ORG in the history, then appears raw in the retrieval context, tripping the egress validator. |
| 5 | QA-005 | High | LLM gap analysis fails 100% (`POST /gap-analysis` -> 502, 5/5). `POST /compare` (document compare) fails or returns raw malformed JSON as the "summary". Evidence shows the model returns malformed JSON despite `guided_json`. The Regulatory Library upload flow swallows the failure silently. |
| 6 | QA-006 | High | Reranking fails 100% of the time (NVIDIA rerank `HTTPStatusError` in ~15-30 ms, then Gemini rerank `GeminiRerankError`); retrieval silently falls back to BM25/RRF order. NVIDIA's own model page states this NIM endpoint is deprecated. The Gemini fallback provider also appears non-functional, so LLM failover is likely not real. |
| 7 | QA-007 | High | Rate limiting is not effective in production (40 parallel requests and 6 x cost-5 requests on a FREE-tier tenant, capacity 10, all succeeded). Combined with open self-registration and LLM-backed endpoints this is a cost-abuse vector. |
| 8 | QA-008 | Medium | Gap analysis, policy checks and the RAG corpus each use their own hardcoded, mutually inconsistent regulatory thresholds; none read the standards catalog. |
| 9 | QA-009..QA-016 | Medium | Real regulator vocabulary masked ("Basel III IRB" -> `[ORG_1]`); UAE phone numbers not masked; Privacy Inspector log empty ~58% of the time (multi-process registry); `PUT /settings` accepts invalid values; mobile (375 px) header/menu defects; answers rendered as raw markdown; answers truncated at 1024 tokens; Regulatory Q&A latency 8-29 s. |
| 10 | QA-017..QA-026 | Low | Escape does not close overlays; empty question accepted; refresh-token replay; public `/docs`; stale status after last-document delete; misleading eval banner; etc. |

What works (PASS): register / login / logout / session persistence / token refresh, dashboard KPIs, notifications (create on upload, unread dot, mark read), global search for models and documents, profile edit, settings save and restore (re-score on save), model creation with PDF and DOCX, metric extraction and policy scoring, document delete, model lineage and new version (409 on duplicate), compare models, JSON export with options, AI Analyst streaming (single-turn), citations navigation, chat history reload, feedback (thumbs, tags, masked comment), RAG Performance dashboard / traces / trace detail / golden dataset CRUD / evaluation run and results, no horizontal page scroll at 375 px.

---

## 2. Method and environment

- Frontend: repo `frontend/` built by Vite locally (`npx vite --config vite.qa.config.ts --port 5173`), proxying `/api` -> `http://modelaudit-alb-1304868163.us-east-1.elb.amazonaws.com` with the same `/api` rewrite as `frontend/vercel.json`. This is the same frontend code talking to the real production backend and production data. The temp config was an untracked copy of `vite.config.ts` with the proxy target changed; it was deleted at the end.
- Driver: Playwright 1.56.1 (Chromium, headless), viewport 1440x900 (desktop) and 375x800 (mobile). Scripts and harness live in the scratchpad `qa/` directory (`t01_auth.cjs` ... `t24_overview.cjs`). Network calls (method, path, status, snippet) and console errors were captured for every step. API-level checks were done with curl using a bearer token.
- Why the Vercel URL was not used directly: this session's network policy blocks `creditaudit-8rht0lyiq-shaktishubhankar.vercel.app` (proxy 403) and I did not try to route around it. The Vercel rewrite `/api/:path*` -> ALB is reproduced by the Vite proxy.
- Backend under test: ALB `GET /health` -> `{"status":"ok","db":"connected"}`. The live OpenAPI lists 49 operations including `/rag/*` and `/query/sessions`, i.e. the post-PR#2 backend. I could not read the ECS task's image tag (AWS MCP unavailable, see section 7), so a backend SHA match with local `main` is **inferred, not verified**.
- Deployed frontend vs local: Vercel MCP `get_deployment` for `dpl_eNfuDfpF8fytX1S3qf6JcDWsNcGJ` (`creditaudit-8rht0lyiq-shaktishubhankar.vercel.app`, target production, state READY, source cli) reports `githubCommitSha = 48816f7cfc00df73ccfd2089e4fa4d822879160a`, message "Merge pull request #2 from Shakti8125/claude/eager-mendel-u8o13f", ref `main`. Local `main` is `48816f7`. **No mismatch.**
- Test data: two synthetic fixtures generated with reportlab / python-docx (fictional Gini/AUC/KS/PSI, no real entity names): `qa_synthetic_pd_validation_v1.pdf` (PASS metrics), `qa_synthetic_pd_validation_v2.pdf` / `.docx` (BREACH metrics). No fixtures exist under `backend/tests/`.
- LLM usage (modest): about 8 regulatory Q&A calls, about 7 AI Analyst turns, 5 gap-analysis attempts, 3 compare attempts, one RAG evaluation run (dense only, top-k 5, generation off, 22 embed calls).

## 3. Credentials used

| Item | Value |
|---|---|
| Documented demo account | `lead_validator@fab.ae` / `Password123!` (from `deployment_steps.md`). **Does not exist in production**: `POST /auth/login` -> 401 "Invalid email or password" (screenshots/02-login-demo-fail.png). |
| Test account (registered through the app's Register UI) | **Email** `qa.agent.20260930@example.com` **Password** (shared privately in the session, not stored in the repo) **Tenant/Organization** `QA Test Tenant` (role ADMIN, auto-assigned) |
| Profile after test | Full name "QA Agent", title "Automation Tester", division "Quality Assurance" |

The user can reuse the test account. It holds two test models (see section 8).

---

## 4. Coverage matrix

Legend: PASS / FAIL / PARTIAL / NOT TESTED / N/A (element does not exist). "Ref" links to findings in section 5.

| # | Page | Element | Result | Ref / note |
|---|---|---|---|---|
| A1 | Login | Sign in (valid) | PASS | |
| A2 | Login | Sign in (wrong password / unknown user) | PASS | 401 "Invalid email or password" (same message for both) |
| A3 | Login | Documented demo account | FAIL | QA-024 (account does not exist) |
| A4 | Register | Create account (email, org, password) | PASS | 200; ADMIN role; new tenant |
| A5 | Register | Weak password (<8 chars) | PASS | 422 surfaced as "password: String should have at least 8 characters" |
| A6 | Register | Duplicate email | PASS | 400 "Email already registered" (user enumeration, QA-021) |
| A7 | Login/Register | "Create an account" / "Sign in" switch links | PASS | |
| A8 | Session | Reload keeps session | PASS | |
| A9 | Session | Access token corrupted -> refresh | PASS | `/users/me` 401 -> `/auth/refresh` 200 -> retry OK |
| A10 | Session | Both tokens invalid -> login screen | PASS | |
| A11 | Session | Logout (sidebar) | PASS | tokens cleared |
| A12 | Session | Logout on mobile | FAIL | QA-013 (no Logout in mobile menu) |
| B1 | Overview | KPI cards (models, documents, issues, AI reviews) | PASS | values match data; "50% without open findings" computed |
| B2 | Overview | Status filter chips ALL/PASS/WARNING/BREACH/PENDING | PASS | |
| B3 | Overview | Model card / Open | PASS | opens workspace |
| B4 | Overview | New Audit CTA (2 places) | PASS | |
| B5 | Overview | Empty state | PASS | |
| C1 | SideNav | 6 nav items, New Audit, Profile, Guidelines, Logout | PASS (desktop) | |
| C2 | TopNav | Global search: models / documents | PASS | click navigates |
| C3 | TopNav | Global search: standards | FAIL | QA-002 (catalog empty; "CBUAE", "Basel" -> "No matches found") |
| C4 | TopNav | Search input special chars (`%`, `' OR 1=1 --`) | PASS | no error, no injection effect |
| C5 | TopNav | Model selector dropdown | PASS | |
| C6 | TopNav | Zero-Trust Privacy Inspector button | PASS (desktop) / FAIL (375 px) | QA-013 |
| C7 | TopNav | Model Lineage button | PASS (desktop) / FAIL (375 px) | QA-013 |
| C8 | TopNav | Notifications bell + unread dot | PASS | count 3 -> 2 after read |
| C9 | TopNav | Mobile hamburger menu | PARTIAL | QA-013 |
| D1 | Notifications drawer | list, click -> mark read -> open workspace | PASS | `POST /notifications/{id}/read` 200 |
| D2 | Notifications drawer | close via X / backdrop | PASS | |
| D3 | Notifications drawer | close via Escape; keyboard access to items | FAIL | QA-017 |
| E1 | Profile modal | view | PASS | |
| E2 | Profile modal | edit + save (persists after reload) | PASS | `PATCH /users/me` 200; 120-char limit enforced |
| E3 | Help modal ("Guidelines") | open/close | PASS | copy inaccurate, see QA-003 |
| F1 | Settings | sliders + Save Configuration (re-score) | PASS | `PUT /settings` 200; restored to original |
| F2 | Settings | server-side validation | FAIL | QA-012 |
| F3 | Settings | read-only masking panel | PASS | |
| G1 | New Audit modal | open (sidebar, overview CTA, mobile menu) | PASS | |
| G2 | New Audit modal | required-name validation, X close, backdrop close | PASS | |
| G3 | New Audit modal | create with PDF (first run 38 s cold, Docling) | PASS | 3 chunks, metrics extracted |
| G4 | New Audit modal | create with DOCX | PASS | 1.9 s |
| G5 | New Audit modal | invalid file types / empty file (via Library) | PASS | 400 messages shown |
| H1 | Workspace | Metrics tab (cards, deciles chart/table) | PASS | |
| H2 | Workspace | Gap Analysis tab: policy threshold checks | PASS | |
| H3 | Workspace | Gap Analysis tab: "Run analysis" (LLM) | FAIL | QA-005; error shown on this tab |
| H4 | Workspace | Documents tab: list, viewer, Browse/Compare toggle | PASS | |
| H5 | Workspace | Documents tab: Delete (confirm dismiss / accept) | PASS | own doc; 204 |
| H6 | Workspace | Document compare (LLM) | FAIL | QA-005 |
| H7 | Workspace | AI Analyst: quick actions (Extract Metrics, Summarize Methodology) | PASS (single turn) | |
| H8 | Workspace | AI Analyst: "Run Gap Analysis" chip | FAIL | QA-005 |
| H9 | Workspace | AI Analyst: free-text send, streaming | PASS (turn 1) / FAIL (turn 2+) | QA-004 |
| H10 | Workspace | Chat citations chips / Citations tab click | PASS | opens Documents tab for the cited doc |
| H11 | Workspace | Chat history reload; New conversation button | PASS | history hydrated after reload |
| H12 | Workspace | Feedback thumbs up / down / tags / comment / remove | PASS | comment masked server-side |
| H13 | Workspace | Answer rendering (markdown) | FAIL | QA-014 |
| H14 | Workspace | Compare button, Export Report button | PASS | |
| I1 | Compare Models | two selectors, baseline vs challenger, self-compare | PASS | |
| J1 | Model lineage modal | version list, New version (201), duplicate (409 message), close | PASS | Escape does not close (QA-017) |
| K1 | Export modal | Include audit trail / citations, Download JSON | PASS | keys: model_info, history, documents, chat_citations |
| L1 | Privacy Inspector | Live redaction simulator | PARTIAL | phone not masked (QA-010) |
| L2 | Privacy Inspector | Entity redaction log for chat session | PARTIAL | non-deterministic (QA-011) |
| L3 | Privacy Inspector | Copy masked token | PASS | |
| M1 | Regulatory Library | Analyze a Model Document (upload + score + gap analysis) | PARTIAL | upload/score PASS; gap analysis fails silently (QA-005/QA-023) |
| M2 | Regulatory Library | Regulatory Q&A form (Ask) | PARTIAL | works via BM25 fallback only (QA-001, QA-003, QA-006); raw markdown, truncation |
| M3 | Regulatory Library | Q&A citations | PARTIAL | not clickable, no snippet (QA-016) |
| M4 | Regulatory Library | Q&A feedback control | PASS | |
| M5 | Regulatory Library | Guardrail-blocked question error | PASS | 400 message shown |
| M6 | Regulatory Library | Standards catalog list / expand clauses | FAIL | QA-002 (empty) |
| M7 | Regulatory Library | Filters on the standards list | N/A | no filter UI exists |
| M8 | Regulatory Library | Standard detail | N/A | no detail endpoint/page; only inline clause expand from list payload |
| M9 | Regulatory Library | Citation/search -> focus standard | NOT TESTED | nothing to focus (catalog empty) |
| N1 | RAG Performance | window 24h/7d/30d/90d, surface filter, Refresh | PASS | |
| N2 | RAG Performance | KPIs, latency waterfall, volume, feedback, providers, scorers | PASS | shows the health warnings for this very problem |
| N3 | RAG Performance | Recent traces table, status filter, Only mine, paging | PASS | |
| N4 | RAG Performance | Trace detail drawer | PASS | Escape does not close (QA-017) |
| N5 | RAG Performance | Offline evaluation: launcher, mode selection, run, poll | PASS | 1 run only |
| N6 | RAG Performance | Eval results drawer, comparison view, case matrix | PASS | |
| N7 | RAG Performance | Golden dataset: view, search, add, edit, delete case | PASS | temp case removed |
| N8 | RAG Performance | Delete run | PASS | 204 |
| N9 | RAG Performance | Restore defaults, activate toggle, run with generation on, cancel run | NOT TESTED | avoided extra LLM/production writes |
| O1 | Responsive 375 px | Horizontal page scroll on all pages | PASS | scrollWidth == clientWidth everywhere |
| O2 | Responsive 375 px | Header layout, mobile menu completeness | FAIL | QA-013 |
| P1 | API | `/regulatory/standards`, `/regulatory/search` | see section 6 | only two regulatory endpoints exist |
| P2 | Security | auth required, CORS preflight from foreign origin | PASS | 401 / 400 |

---

## 5. Detailed findings

Conventions: paths are relative to `/home/user/creditAudit`. "Hypothesis" is stated explicitly wherever the cause could not be confirmed from evidence (CloudWatch was unavailable).

### QA-001 (Critical) - Regulatory vector index `cbuae-manuals` is empty; dense retrieval never returns regulatory passages

- Page/element: Regulatory Library -> Regulatory Q&A; AI Analyst; RAG Performance; `POST /regulatory/search`.
- Repro: log in, Regulatory Library, ask "Summarise the PD validation requirements in the CBUAE MMG"; open RAG Performance -> Recent traces -> that trace.
- Expected: dense candidates from Pinecone namespace `cbuae-manuals` fused with BM25 and reranked; citations of retrieval_method `dense`/`hybrid_rrf`/`*_reranked`.
- Actual: `dense_count = 0`, `dense_empty = true`, `bm25_count = 10`, `fused_count = 10`; every citation is `bm25` and `CBUAE-MMG-2022 / Section N` (the hardcoded array).
- Evidence:
  - Trace `e2162c68-1147-4d4f-aa5d-b70327434fea` (`GET /rag/traces/{id}`): `dense_ms 352`, `llm_calls[0] = embed / nvidia / nvidia/nemotron-3-embed-1b / 276 ms / success`; `dense_count 0`; `score_kind bm25`.
  - RAG Performance banner (screenshots/11-empty-rag-performance.png): "Dense retrieval returned no candidates for most requests - check Pinecone/embedding configuration. Results are BM25-only." KPI "Dense empty 83%".
  - Offline evaluation, one run (mode `dense`, k=5, generation off, all 22 golden cases): Hit@5 = 0.00, Recall = 0.00, MRR = 0.00, nDCG = 0.00, 22/22 cases "miss" (screenshots/132-eval-done.png, 133-eval-results-drawer.png).
  - **Pinecone and embeddings are healthy** (this discriminates the cause): a document-scoped chat trace `a09494b6-0950-4303-8a97-ce13aaafe22d` has `dense_count = 3` = exactly the 3 chunks of the uploaded synthetic document (namespaces queried: `cbuae-manuals` + `user-docs:{tenant}:{doc}`), and the upload path upserted vectors without error. So key, index name, dimension, embedding provider and network all work; the `cbuae-manuals` namespace simply contains no vectors.
- Root cause (confirmed by code + evidence):
  - `backend/scripts/index_regulatory_corpus.py:14-17` reads PDFs from `backend/base_documents/` and, if the directory is missing, prints "Directory not found" and returns (exit code 0).
  - `.gitignore:33` ignores `backend/base_documents/`; the directory does not exist in the repo (`git ls-files` has no PDFs). `backend/Dockerfile:31` does `COPY . .` from the CI checkout, so the image cannot contain the manuals. Running the documented ECS one-off command (`deployment_steps.md` 566-575) would therefore print "Directory not found" and "succeed".
  - No workflow runs the script: `.github/workflows/deploy-production.yml` only runs `alembic upgrade head` as a one-off task; `grep -r index_regulatory .github` finds nothing. HANDOFF.md section 7 step 4 lists it as a manual TODO ("Make sure the regulatory corpus is indexed in Pinecone") that was never confirmed.
  - The source regulatory PDFs are not in the repository at all, so a re-index needs the documents from the owner.
- Impact: all regulatory retrieval is BM25 over 10 paragraphs; dense/hybrid/rerank evaluation is meaningless; the golden dataset (targets are `CBUAE-MMG-2022 / Section N`, the hardcoded corpus) can only ever be satisfied by BM25.

### QA-002 (High) - `regulatory_standards` catalog is empty in production

- Page/element: Regulatory Library -> "Regulatory Guidelines Catalog"; global search; citation/search "open standard".
- Repro: open Regulatory Library.
- Expected: 4 standards from `seed_regulatory_standards.py` (CBUAE MMG §4.2, IFRS 9 ECL, FRB SR 11-7 / OCC 2011-12, Basel III/IV IRB) as promised by `deployment_steps.md` smoke test #4.
- Actual: "No regulatory standards available." `GET /regulatory/standards` -> `200 {"standards":[]}` (also for a brand-new tenant; the table has no tenant column, so it is empty for everyone). Global search for "CBUAE", "Basel" -> `{"results":[]}` -> "No matches found." (screenshots/11-empty-regulatory-library.png).
- Root cause: the seed script (`backend/scripts/seed_regulatory_standards.py`) has never been run against production and no pipeline step runs it (`.github/workflows/deploy-production.yml` has only the Alembic step; the seed is only in `deployment_steps.md` 550-563 and HANDOFF.md section 7 step 3). `backend/app/api/regulatory.py:116-126` and `backend/app/api/system.py:~236-290` (search) just read the table.
- Note: the table is a UI-only reference list. See QA-008: nothing in RAG, gap analysis or policy checking reads it, so seeding it alone will not fix analysis quality.

### QA-003 (High) - Document-scoped AI Analyst has no regulatory context, contrary to UI/help copy

- Page/element: Workspace -> AI Analyst; Help modal; Workspace header line "Grounded in <file> and the regulatory corpus".
- Repro: open a model with an analysed document, AI Analyst, ask "What does the CBUAE MMG require for PSI thresholds and does this model comply?" (or the API: `POST /query` with `model_version_id`).
- Expected: answer cites the MMG PSI bands (the hardcoded Section 6 says PSI < 0.10 / 0.10-0.25 / >= 0.25) and compares with the model's PSI.
- Actual: "The CBUAE MMG-specific PSI threshold is not stated in the provided context, so the exact requirement cannot be determined ... compliance cannot be affirmed or denied." Citations were only the 3 chunks of the uploaded document (`hybrid_rrf`).
- Evidence: `logs/q_A.txt`; trace `a09494b6-...` (`dense_count 3`, `bm25_count 3`, all sources are the uploaded file). Copy: `frontend/src/components/WorkspaceView.tsx:1024,1063`, `frontend/src/components/HelpModal.tsx:23`.
- Root cause: `backend/app/services/retrieval/hybrid_retriever.py:208-229` - when `document_id` is set, BM25 searches only that document's chunks; the hardcoded regulatory corpus is used only in the `else` branch (`:230-243`, `document_id is None`). The dense side queries `["cbuae-manuals", user-docs...]` (`:286-288`) but `cbuae-manuals` is empty (QA-001). Net effect: regulatory grounding for the main chat path is zero.

### QA-004 (High) - 2nd and later turns in a document-scoped chat are blocked with HTTP 422 (egress check)

- Page/element: Workspace -> AI Analyst, second message.
- Repro (UI): AI Analyst -> click "Extract Metrics" (answer cites `[Source: qa_synthetic_pd_validation_v1.pdf, ...]`) -> ask any second question. Reproduced 2/2 (UI: "Unable to complete analysis: Request blocked by the privacy egress check: the prompt would expose a registered entity."; API follow-up "Summarise the calibration results." -> 422). A regulatory-only two-turn conversation (no document) worked.
- Evidence: `POST /query -> 422 {"detail":"Request blocked by the privacy egress check: the prompt would expose a registered entity."}` (screenshots/41-chat-custom-question.png; RAG trace status "blocked", guardrail `egress_violation`). `POST /privacy/mask` on the prior assistant text shows the mechanism: `{"qa_synthetic_pd_validation_v1.pdf": "[ORG_1]"}` is registered as an ORG entity.
- Root cause (confirmed mechanism; egress step inferred from code): `backend/app/api/query.py:309-346` masks the prior conversation history with the session registry, which registers the cited file name as an entity; `:349-352` builds `context_text` from citations with the raw file name (`Source: {c.source}`); `:366` egress-validates the final prompt against that registry and finds the raw file name. First turns are unaffected (empty registry). The system prompt itself instructs the model to cite `[Source: <source_name>...]`, so every answer plants the file name into history.
- Side effect: the blocked user message stays persisted in the session (message_count 3: user, assistant, user) with no reply.

### QA-005 (High) - LLM gap analysis and document compare are unreliable / failing

- Gap analysis: `POST /gap-analysis` -> `502 {"detail":"Failed to generate gap analysis from LLM"}` in 5/5 attempts (1 via Library upload flow, 2 via Gap tab / chip, 2 via API; 6-33 s each).
- Compare: `POST /compare` -> 502 "Generated comparison failed guardrail validation" (UI, 28 s; API try 2) and, on API try 1, `200` with `differences: []` and a `summary` that is the raw model output, which is **malformed JSON** (`"{\n\n{\n  \"differences\": [...` with a stray `,` and cut off mid-table by the 1024-token cap) (`logs/compare_api.txt`).
- Root cause (supported by the compare evidence; hypothesis for the exact provider behaviour): the primary NVIDIA generation model does not honour `guided_json` and emits almost-JSON. `backend/app/services/llm/nvidia_provider.py:141-142` passes `extra_body["guided_json"]`; `max_tokens` defaults to 1024 (`:131`, `router.py:285`). `backend/app/api/gap_analysis.py:130-131` does a strict `json.loads` / `GapAnalysisResponse(**...)` with no fallback, so any malformed output becomes the generic 502 (`:155-158`) (a provider outage would be 503 via `client_http_error`, an egress block 400/422). `backend/app/api/compare.py` falls back to `summary=result_str` on parse failure and then the output guardrail rejects the raw text. CloudWatch would confirm the `JSONDecodeError`; not readable in this session.
- UX: Workspace Gap tab shows "Gap analysis failed: ..." correctly, but the Regulatory Library "Upload & Analyze" flow swallows the error (`frontend/src/components/RegulatoryLibraryView.tsx:185-190`, comment "Non-fatal") and lands on the Gap tab reading "No AI gap analysis has been run for this document yet." (QA-023). The upload notification (PASS/BREACH) is unaffected.
- Also: the gap-analysis checklist is 4 hardcoded strings (QA-008).

### QA-006 (High) - Reranker fails on every request; Gemini fallback appears non-functional

- Evidence: `llm_calls` in every trace: `rerank / nvidia / nvidia/llama-3.2-nv-rerankqa-1b-v2 / 15-29 ms / HTTPStatusError`, then `rerank / gemini / gemini-2.0-flash / 122-356 ms / GeminiRerankError`, then fallback. RAG dashboard: "Reranker fell back to fusion order in 100% of requests", "Rerank fallback 100%". Consequence seen in the first regulatory answer: BM25 order was kept and top-5 excluded Section 5 (PD calibration, rank 6) so the answer said the MMG "does not provide PD-validation-specific technical requirements" (trace `e2162c68-...`).
- Root cause (hypothesis, with external evidence): NVIDIA's model page for `llama-3.2-nv-rerankqa-1b-v2` states "This NIM Endpoint has been deprecated" (build.nvidia.com/nvidia/llama-3_2-nv-rerankqa-1b-v2, retrieved 2026-09-30 via web search snippet). The code calls `https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-3.2-nv-rerankqa-1b-v2/reranking` (`nvidia_provider.py:29-31`); NVIDIA's docs use the `llama-3_2-...` path form. A 15-30 ms `HTTPStatusError` is consistent with a 404/410 from the hosted endpoint. `GeminiRerankError` means Gemini failed to score every passage (`gemini_provider.py:177-182`): likely invalid/expired key or a retired `gemini-2.0-flash` (hypothesis; the provider is "configured", so it is tried).
- Implication for QA-005/QA-004 and resilience: with Gemini failing, generation has no working secondary provider (not tested end-to-end: `LLM failover 0%` only because NVIDIA generation itself worked).

### QA-007 (High) - Rate limiting is not enforced in production

- Repro: with one FREE-tier tenant, `seq 1 40 | xargs -P 20 curl GET /regulatory/standards` -> 40 x HTTP 200. Six parallel `POST /compare` (cost 5 each, bucket capacity 10 for FREE) -> six 404 (the ids were fake, but the limiter dependency runs first) and no 429. During the whole session no 429 was ever seen despite dozens of rapid calls; the deployment guide's smoke test #7 expects 429.
- Root cause (hypothesis): `backend/app/middleware/rate_limiter.py:60` returns allowed when `settings.rate_limit_enabled` is false or the Upstash Redis client is not configured, and `:135-136` fails open on any Redis/Lua error. Either `REDIS_URL/REDIS_TOKEN` are missing/invalid in the ECS task definition, or `RATE_LIMIT_ENABLED=false`, or the script errors. Need the env var names and CloudWatch to decide.
- Impact: `POST /auth/register` is open (anyone becomes ADMIN of a new tenant) and LLM endpoints (`/query`, `/regulatory/search`, `/gap-analysis`, `/compare`, `/rag/eval/runs`) are unmetered -> cost-abuse exposure.

### QA-008 (Medium) - "Regulatory analysis" features do not use the standards catalog; thresholds are inconsistent

- Gap analysis: hardcoded 4-item checklist `backend/app/api/gap_analysis.py:80-85` (Gini >= 40%, PSI <= 0.25, qualitative assumptions, 12-month backtesting); it never retrieves regulatory text.
- Policy checks: hardcoded in `backend/app/services/analytics/policy_checker.py` (AUC PASS >= 0.75 at `:143-156`, KS >= 30, Gini >= 40 + tenant tolerance, PSI from tenant settings).
- BM25 corpus Section 4 (`hybrid_retriever.py`, `CBUAE_REGULATORY_CORPUS`): "AUC-ROC >= 0.70". Seed catalog: "Max 10% Gini Delta", "IV >= 0.02, VIF < 2.5" - none of which exist in the BM25 corpus or the policy checker. Result: the same "CBUAE MMG" is quoted with different numbers depending on the feature (e.g. workspace shows AUC threshold >= 0.75; regulatory Q&A says >= 0.70).
- `RegulatoryStandard` is read only by `GET /regulatory/standards` and `GET /search` (`grep RegulatoryStandard backend/app`). Whether the hardcoded paragraphs faithfully reflect the real CBUAE document could not be verified (no source document available); treat citations as unverified.

### QA-009 (Medium) - Public regulatory names are masked as `[ORG_1]` in regulatory questions

- Repro: `POST /regulatory/search` with "What is the minimum historical data period for PD estimation under Basel III IRB?". RAG trace `query_masked`: "... under [ORG_1]?"; "What does Basel CRE36 say about ..." -> "What does [ORG_1] say ...".
- Impact: the masked text is what goes to BM25, embedding and the LLM, so "Basel III IRB" is lost from retrieval and the answer (Q3) attributed the "5 years" to CBUAE MMG Section 3 without noting the Basel scope.
- Root cause: `backend/app/services/privacy/ner_masker.py:106-119` protects "basel", "irb" as single terms; the composite check `:187-191` requires every word of a spaCy span to be in the vocabulary, so spans such as "Basel III IRB" (roman numeral) or "Basel CRE36" (paragraph id) are still masked. (Cases "IFRS 9" and "CBUAE MMG" pass.)

### QA-010 (Medium) - UAE phone number is not masked

- Repro: Privacy Inspector -> Live Redaction Simulator: "Northwind Credit Bank approved a facility for Jane Testperson with Gini of 0.42, contact jane.test@example.org or +971 50 123 4567." -> output masks org, person, email but leaves `+971 50 123 4567` (screenshots/160-privacy-simulator.png). Settings page and Help claim phone numbers are replaced by `[PHONE_1]`.
- Root cause (hypothesis): Presidio `PHONE_NUMBER` recogniser (`ner_masker.py:232-245`) uses default supported regions that exclude the UAE. Not a real person's number (fictional test data).

### QA-011 (Medium) - Privacy Inspector redaction log is empty about 58% of the time in production

- Repro: chat with entities ("Does Northwind Credit Bank meet the PSI requirement for the Jane Testperson portfolio?"), then `GET /privacy/redactions?session_id=...` x12: 5 responses contained `{"Jane Testperson":"[PERSON_1]","Northwind Credit Bank":"[ORG_1]"}`, 7 returned `{}` (UI showed the log without the chat entities, screenshots/162-privacy-redaction-log.png).
- Root cause: entity registries are per-process memory (`backend/app/services/privacy/registry_store.py`, by design, AGENTS.md) and the production service runs more than one worker/task behind the ALB. Also affects multi-turn placeholder consistency across requests (HANDOFF.md known issue 12). Answers still show raw placeholders (`[ORG_1]`, `[PERSON_1]`) to the user (Low UX).

### QA-012 (Medium) - `PUT /settings` has no server-side validation

- Repro: `PUT /settings {"psi_warning_threshold":0.4,"psi_breach_threshold":0.2}` -> 200; `{"gini_tolerance":-5}` -> 200; `{"psi_warning_threshold":999,"psi_breach_threshold":9999}` -> 200 (values were restored afterwards). The UI slider min/max and `psiOrderInvalid` check exist only client-side. Since saving re-scores every model's current version, bad values silently change compliance statuses.
- Root cause: `backend/app/schemas/system.py:24-32` (`TenantSettingsUpdate`) has plain `float | None` fields.

### QA-013 (Medium) - Mobile (375 px): header and menu defects

- Repro: log in at 375 px. Measured in the DOM: search input width 0 px (unusable); the Zero-Trust Privacy Inspector button (x 179-221) and Model Lineage button (x 231-267) sit under the model selector (x 84-270), `elementFromPoint` at the Privacy button center is the model selector; clicking them times out. The hamburger menu lists the 6 nav items and "+ New Audit" only: Profile, Guidelines and Logout exist only in the desktop `SideNav`. Screenshots: 153-m-header.png, 141-m-menu.png.
- Root cause: `frontend/src/components/TopNav.tsx:158-160` (flex row without wrapping; `max-w-xs` search shrinks to 0), `frontend/src/App.tsx` mobile menu (nav + New Audit only), `frontend/src/components/SideNav.tsx:43` (`hidden md:flex`).
- Passing: no horizontal page scroll on any page at 375 px (Overview, Workspace tabs, Compare, Library, RAG both tabs, Settings, drawers, New Audit modal).

### QA-014 (Medium) - Assistant answers are rendered as raw markdown

- Repro: any AI Analyst answer (tables, bold) or Regulatory Q&A answer. UI shows literal `**bold**`, `| a | b |` table pipes and `<br>` (screenshots/51-library-qa-result.png, 41-chat-custom-question.png); Regulatory Q&A collapses numbered lists into one paragraph.
- Root cause: `frontend/src/components/WorkspaceView.tsx:150` (`whitespace-pre-line` text) and `frontend/src/components/RegulatoryLibraryView.tsx:354` (plain text); no markdown renderer in `frontend/package.json`.

### QA-015 (Medium) - Truncated answers and slow Regulatory Q&A

- Answers end mid-sentence (e.g. Regulatory Q&A "...validation must consider the foundational data quality and development standards"; first API answer ends "Validation"). `max_tokens=1024` is used everywhere (`router.py:285,303`) with a reasoning-type model (`nvidia/nemotron-3-super-120b-a12b`), with no truncation indicator.
- `/regulatory/search` is non-streaming and took 8.7-29 s (p95 23.9 s, p50 9.8 s on the dashboard); the UI shows a spinner only.
- The telemetry citation counter misses citations written with full-width brackets (`【Source: ...】`) that the model sometimes emits -> `answer_citation_count = 0` (trace `a09494b6-...`). Low.

### QA-016 (Low) - Regulatory Library UX gaps

- Q&A citations show source + section only: not clickable, no snippet, and no indication that the answer is BM25-only or that the retrieved set is a 10-paragraph fallback (`RegulatoryLibraryView.tsx` citation block).
- No filters and no standard-detail page/endpoint exist (only `GET /regulatory/standards` and `POST /regulatory/search`).
- RAG evaluation comparison banner says "Pinecone or embedding provider unreachable" (`frontend/src/components/rag/EvalRunComparison.tsx:217-218`) when the actual cause is an empty namespace; misleading.

### QA-017 (Low) - Overlays ignore Escape; notification rows are not keyboard-accessible

- Escape does not close the Privacy Inspector, Lineage modal, Export modal, Notifications drawer or Trace drawer (no `keydown` handler anywhere in `frontend/src/components`). Notification rows are `div onClick` (`NotificationsDrawer.tsx:156`) without `role`/`tabindex`.

### QA-018 (Low) - Empty question is accepted by `/regulatory/search`

- `POST /regulatory/search {"question":""}` -> 200 with an LLM answer "no regulatory context or specific question was provided" (an LLM call and trace with 0 context, RAG trace "—"). `RegulatoryQuery.question` in `backend/app/schemas/regulatory.py` has no min length. The UI disables Ask on empty input.

### QA-019 (Low) - Auth hardening

- Refresh tokens are not rotated/revoked: an old refresh token was accepted twice after a newer one was issued (`POST /auth/refresh` 200, 200). Register discloses existing emails ("Email already registered"). Self-registration creates a tenant with ADMIN role and no verification. The password limit (72) matches bcrypt.

### QA-020 (Low) - API docs are public

- `GET /docs`, `/redoc`, `/openapi.json` on the ALB return 200 without auth (full route list is visible). CORS preflight from a foreign origin is correctly rejected (400).

### QA-021 (Low) - Known backlog items verified live

- Deleting a model's last document leaves status/metrics: Model 02 stayed `BREACH` with 6 policy results, dashboard `compliance_issues = 1` and `documents_analyzed = 0`, card says "Not analyzed yet" (HANDOFF known issue 2).
- After "New version", documents of the older version are hidden in the Documents tab and cannot be deleted from the UI (issue 3); I removed them via `DELETE /documents/{id}`.
- User-message orphan after a blocked chat turn (QA-004 side effect).

### QA-022 (Low) - Documentation drift

- `deployment_steps.md` smoke test #6 expects a `suggestedActions` SSE event; the stream now emits `session_id`, `trace`, `citations`, `token`*, `done`. Smoke test #5/#8 mention ROC chart (already noted as HANDOFF issue 14).

### QA-023 (Low) - Library "Upload & Analyze" hides a failed AI gap analysis

- See QA-005: error swallowed at `RegulatoryLibraryView.tsx:185-190`, status text says "Analysis complete." even though the AI gap analysis failed.

### QA-024 (Info) - Documented demo account does not exist

- `lead_validator@fab.ae` / `Password123!` returns 401 in production. `deployment_steps.md` (lines 943, 997) should be updated or the account provisioned.

### QA-025 (Info) - External font dependency (environment note)

- Google Fonts (Inter, Material Symbols) are loaded from `fonts.googleapis.com` (`frontend/index.html`). In this sandbox they are blocked (console `ERR_CERT_AUTHORITY_INVALID`), so icons rendered as ligature text ("model_training", "timeline", "description") in the Gap tab (screenshots/30-ws-tab-gapanalysis.png, `WorkspaceView.tsx:844`). This is an artifact of the sandbox, not a production defect, but the Gap tab has no fallback if the font CDN is unavailable.

### QA-026 (Info) - First upload latency

- First PDF upload took ~38 s (Docling cold start); later uploads 2-3 s. No spinner text beyond "Creating audit".

---

## 6. Regulatory corpus diagnosis (per layer)

### Endpoints (from `backend/app/api/regulatory.py`)

Only two regulatory endpoints exist: `GET /regulatory/standards` (list all, no filters, no detail) and `POST /regulatory/search` `{question}` -> `{answer, citations[], trace_id}`. There is no `/regulatory/standards/{id}`, no filter parameters and no `/regulatory/*` admin/ingest endpoint.

### Layer 1 - Standards catalog (Postgres `regulatory_standards`)

| Item | Finding |
|---|---|
| Populated in production? | **No.** `GET /regulatory/standards` -> `{"standards":[]}` (HTTP 200, 0.11 s). Table has no tenant column, so it is empty for all tenants. |
| Should contain | 4 rows from `backend/scripts/seed_regulatory_standards.py` (`REGULATORY_STANDARDS`, codes "CBUAE MMG §4.2", "IFRS 9 ECL", "FRB SR 11-7 / OCC 2011-12", "Basel III/IV IRB"). |
| Why empty | Seed is idempotent but manual; not in `.github/workflows/deploy-*.yml` (only Alembic); never executed. |
| Effects | Library catalog empty; search never returns standards; "open standard" navigation dead; `deployment_steps.md` smoke test #4 would fail. No RAG/analysis path depends on it. |

### Layer 2 - Vector index (Pinecone `cbuae-manuals`)

| Item | Finding |
|---|---|
| What the script indexes | `backend/scripts/index_regulatory_corpus.py`: every `*.pdf` in `backend/base_documents/` -> Docling markdown -> `MarkdownChunker(2400, 400)` -> `LLMRouter.embed(input_type="document")` (NVIDIA `nvidia/nemotron-3-embed-1b`) -> `PineconeStore.upsert_vectors(namespace="cbuae-manuals")` in batches of 50 (metadata: source=PDF file name, section=header path or "Chunk i", text). Namespace `cbuae-manuals` is what `HybridRetriever` queries (`hybrid_retriever.py:286`). User docs use `user-docs:{tenant}:{document}`. |
| Source documents exist in repo? | **No.** `backend/base_documents/` is gitignored (`.gitignore:33`), absent from the repo and therefore from the Docker image (`backend/Dockerfile:31`). The script silently exits with "Directory not found" (`:15-17`). No PDF exists anywhere in the repo. |
| Populated in production? | **No** (empty or non-existent namespace). Evidence: `dense_count = 0` on every regulatory trace; 22/22 golden cases miss in dense mode; while `user-docs:*` namespaces on the same index return vectors (`dense_count = 3`). |
| Is Pinecone/embedding broken? | **No.** Embedding call succeeds (~150-280 ms, NVIDIA), upsert of user-doc chunks succeeds (so API key, index name and 1024-dim compatibility are fine), query returns the user-doc vectors. No errors surfaced in any response. CloudWatch (missing key/Pinecone errors, `EgressViolationError`, etc.) could not be read: AWS MCP required re-authentication. |
| Whether any one-off seed/index ECS task ever ran | Could not be checked (AWS unavailable). The evidence shows the outcome (empty), consistent with never run or run with a missing directory (silent success). |

### Layer 3 - BM25 fallback (`CBUAE_REGULATORY_CORPUS`)

| Item | Finding |
|---|---|
| Location | `backend/app/services/retrieval/hybrid_retriever.py:38` (10 hardcoded sections, source `CBUAE-MMG-2022`, "Section 1 ... Section 10"). |
| Used when | only when `document_id is None` (`:230-243`), i.e. `POST /regulatory/search` and chat without a document. Not used for document-scoped chat (QA-003). |
| Behaviour | Works: all regulatory Q&A citations in production come from here. BM25 returns all 10 items including zero-score ones (`bm25_count = 10` always), top_k=5 truncates; with the reranker failing (QA-006) relevant sections can be dropped (Section 5 ranked 6th for a PD question). |
| Quality | Paragraph-level summaries, not the full regulation; cannot answer Basel IRB, IFRS 9 details beyond one paragraph, etc. The answer to "Basel III IRB minimum data period" was attributed to CBUAE Section 3. Fidelity to the real MMG is unverified. |

### Layer 4 - Answer path when layers are empty

| Condition | Observed behaviour |
|---|---|
| Dense empty (production now) | Silent degrade: `dense_empty` recorded in the trace, no error to the user, no notice in the UI; answer is generated from the BM25 subset with citations (all `bm25`). `HybridRetriever.retrieve` catches dense exceptions and continues (`:294-306`); `PineconeStore._query_sync` returns `[]` on any error (`pinecone_store.py`). |
| Reranker failing (production now) | Silent fallback to fused order (`reranker.py`), `rerank_fallback=true` in the trace. |
| Question outside the corpus | Not a hallucination in my probes: "Basel CRE36 output floor" -> "there is no mention ... in any of the cited sections". Empty question -> generic apology (200). Off-scope answers still carry 5 irrelevant `CBUAE-MMG-2022` citations (citation list is not filtered by relevance). |
| Document-scoped chat | No regulatory context at all (QA-003); the model correctly says the requirement "is not stated" - i.e. useless for compliance checking but not a hallucination. |
| Hard failures | No 500s observed. Egress block -> 422 (QA-004), provider outage would be 503, jailbreak/injection -> 400. |
| Both BM25 and dense empty | Not reachable for the regulatory path (BM25 corpus is code). For a document with zero chunks the prompt has empty context (not tested). |

### What "regulatory analysis" features depend on today

| Feature | Depends on | State in production |
|---|---|---|
| Regulatory Q&A + citations | 10 hardcoded paragraphs (BM25) + LLM; Pinecone `cbuae-manuals` (empty); rerank (failing) | Works, low fidelity |
| AI Analyst regulatory grounding | Nothing (doc-scoped) / same as Q&A (no doc) | Broken for doc-scoped (QA-003) |
| LLM gap analysis vs "CBUAE MMG checklist" | 4 hardcoded checklist strings + uploaded doc text + LLM structured JSON | Failing (QA-005); does not use any corpus |
| Policy threshold checks (PASS/WARNING/BREACH) | `policy_checker.py` constants + tenant settings | Works; independent of the corpus |
| Regulatory catalog / search / "open standard" | `regulatory_standards` table | Empty (QA-002) |
| RAG evaluation | Golden dataset targets on `CBUAE-MMG-2022 / Section N` (the hardcoded corpus) | Runs; dense metrics all zero |

### Root cause summary with file:line

1. `backend/scripts/index_regulatory_corpus.py:14-17` requires `backend/base_documents/*.pdf`; `.gitignore:33` excludes it; `backend/Dockerfile:31` cannot include it; the CBUAE PDFs are not in the repository; no deployment step runs the script (`.github/workflows/deploy-production.yml` only runs Alembic).
2. `backend/scripts/seed_regulatory_standards.py` (whole file) is never run by any pipeline; `backend/app/api/regulatory.py:116-126` returns the empty table.
3. `backend/app/services/retrieval/hybrid_retriever.py:208-243` restricts the hardcoded corpus to non-document queries; `:286-288` dense namespaces.
4. `backend/app/services/llm/nvidia_provider.py:29-31` (deprecated hosted reranker) and `gemini_provider.py:177-182` (all passages failed) -> reranker fallback 100%.

---

## 7. What could not be tested, and why

- **AWS / CloudWatch / ECS (read-only)**: the AWS MCP server returned "needs you to sign in again" on both attempts and cannot be re-authenticated non-interactively. Therefore not verified: CloudWatch errors (Pinecone/vector-store errors, `EgressViolationError`, `AllProvidersUnavailableError`, JSON parse tracebacks), ECS task definition env var names (`PINECONE_*`, `REDIS_*`, `RATE_LIMIT_ENABLED`, `GEMINI_API_KEY`), running task count, image tag/backend SHA, and whether a one-off seed/index task ever ran. Hypotheses in QA-005, QA-006, QA-007 need this confirmation.
- Direct Pinecone inspection (`describe_index_stats`) - no credentials; inferred from behaviour (QA-001).
- Cross-tenant isolation - would require a second production tenant; not created.
- Real CBUAE/Basel/IFRS source documents - not in the repo; fidelity of the hardcoded corpus not verified.
- 50 MB upload limit, scanned-PDF OCR, very large documents, concurrent uploads.
- RAG evaluation with generation on / LLM judge, multi-mode comparison, run cancel, "Restore defaults", activate/deactivate toggles (kept to a single small run as instructed).
- SSE mid-stream failure/cancel handling, provider failover under an NVIDIA outage.
- Citation-to-standard navigation (`onOpenRegulatoryStandard`) - no standards to open.
- Vercel-hosted UI itself (blocked); Vercel `/api` rewrite behaviour reproduced only via the Vite proxy.

## 8. Cleanup performed

Created in production by this session and removed:
- 3 uploaded documents (2 via API, 1 via UI; `qa_synthetic_pd_validation_v1.pdf`, `..._v2.pdf`, `..._v2.docx`) - all deleted, `GET /documents` returns `[]`. (Pinecone `user-docs:*` namespaces are deleted by the endpoint, `documents.py:494`; not independently verified.)
- 1 temporary RAG golden case (created, edited, deleted; dataset back to 22 defaults) and 1 evaluation run (deleted, `DELETE` 204).
- 2 feedback votes on my own traces (deleted).
- Settings changed and **restored** to the original values (`gini_tolerance 0.05`, `psi_warning_threshold 0.1`, `psi_breach_threshold 0.25`; verified via `GET /settings`; `updated_at` changed only).

Left behind (no delete endpoint exists in the API; all inside the test tenant `QA Test Tenant`, safe to delete from the database):
- The tenant, the user `qa.agent.20260930@example.com` (profile edited), and tenant settings.
- Two models: "QA Test Model 01 - Retail PD Scorecard" (versions 1.0 archived and 2.0-qa current; status PENDING) and "QA Test Model 02 - LGD Challenger" (status BREACH, stale metrics after its document was deleted).
- Chat sessions/messages (5 assistant answers, including one blocked turn), 17+ RAG traces (masked query text only), notifications (3 upload notifications, 1 read).

Local: `frontend/vite.qa.config.ts` deleted; Vite dev server stopped; `git status` is clean (no tracked file modified, no commit, no push). This report is the only new file (`docs/qa/live-app-audit-2026-09-30.md`, untracked).
