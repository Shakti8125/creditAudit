# ModelAudit AI — Frontend Implementation Plan

Goal: build a React frontend that is API-compatible with the current backend (`backend/`) and visually/functionally matches the reference UI at `modelaudit-ai/`.

---

## 1. Reference UI inventory (what we are replicating)

Framework: **React 19 + TypeScript 5.8 + Vite 6 + Tailwind CSS v4 + lucide-react + motion**.

5 views + 7 modals/drawers + 2 shell components (from `modelaudit-ai/src`):

| Type | Component | Key data consumed |
|------|-----------|-------------------|
| Shell | `SideNav`, `TopNav` | model list, current model, global search (TopNav), storage widget |
| View | `OverviewView` | `ModelSummary[]`, headline stats (active models / docs / compliance issues / AI reviews), search + status filter |
| View | `WorkspaceView` | current model metrics, ROC curve, PSI deciles, gap-analysis requirements, AI-analyst chat (SSE) |
| View | `CompareModelsView` | baseline vs challenger (`ComparisonModel`) |
| View | `RegulatoryLibraryView` | `RegulatoryStandard[]` catalog + document upload → analyze |
| View | `SettingsView` | thresholds + zero-trust toggles |
| Drawer | `PrivacyInspectorDrawer` | `RedactedEntity[]` log + live mask simulator |
| Drawer | `NotificationsDrawer` | `Notification[]` list |
| Modal | `NewAuditModal` | create model (name, type, algorithm, portfolio, description) + upload doc |
| Modal | `ModelLineageModal` | version genealogy (version/title/author/status/gini/isCurrent) |
| Modal | `ExportReportModal` | export pdf/docx/json + includeCitations + includeAuditTrail |
| Modal | `ProfileModal` | validator profile (role/division/clearance/accreditation) |
| Modal | `HelpModal` | static reference |

The source-of-truth DTOs are in `modelaudit-ai/src/types.ts`.

---

## 2. Backend API surface (current, verified)

Base: `http://localhost:8001` (uvicorn, per Dockerfile). All routes except `/auth/*` and `/health` require `Authorization: Bearer <JWT>`.

### Auth (no auth required)
- `POST /auth/register` `{email, password, tenant_name}` → `TokenResponse {access_token, refresh_token, token_type, expires_in}`
- `POST /auth/login` `{email, password}` → `TokenResponse`
- `POST /auth/refresh` `{refresh_token}` → `TokenResponse`
- `GET /health` → status

### Models
- `GET /models` → `ModelSummary[]`
- `POST /models` `{name, type, description, initial_version}` → `ModelSummary`
- `GET /models/{id}` → `ModelSummary`
- `GET /models/{id}/versions` → `ModelVersionDTO[]`
- `GET /models/{id}/export-data` → `ModelExportData {model_info, history}`
- `GET /models/{id}/metrics/population-deciles` → `{deciles: [{decile, expected, actual}]}`
- `POST /models/compare` `{model_id_a, model_id_b}` → `{baseline, challenger}` (each `ComparisonModelDTO`)

### System
- `GET /dashboard/metrics` → `{active_models, documents_analyzed, compliance_issues}`
- `GET /settings` / `PUT /settings` → `TenantSettings`
- `GET /notifications` → `NotificationResponse[]`
- `GET /search?q=` → `{results: [{id, type: 'model'|'regulatory_standard', title, description}]}`
- `GET /users/me` → `UserProfileResponse`

### Documents
- `POST /documents/upload` (multipart: `file`, `model_version_id` form field) → `UploadResponse {document_id, filename, file_type, page_count, chunk_count, masking_report, metrics_summary}`
- `GET /documents` → `{documents: DocumentMetadata[]}`
- `GET /documents/{id}` → `{id, filename, status, metrics_summary, chunks[{index, text}]}`
- `DELETE /documents/{id}`

### Analytics
- `POST /gap-analysis` `{document_id}` → `{gaps: ComplianceGap[], coverage_score}`
- `POST /compare` `{document_id_a, document_id_b, focus_areas[]}` → `{differences: ComparisonDifference[], summary}`

### Regulatory
- `GET /regulatory/standards` → `{standards: RegulatoryStandardResponse[]}`
- `POST /regulatory/search` `{question}` → `{answer, citations}`

### Privacy
- `POST /privacy/mask` `{text, session_id?}` → `{masked_text, redactions: {raw -> masked}}`
- `GET /privacy/redactions?session_id=` → `{session_id, redactions: {raw -> masked}}`

### AI Analyst (SSE)
- `POST /query` `{question, document_id?, session_id?}` → SSE stream. Events (each line `data: {json}\n\n`):
  - `{"type":"session_id","content":"<uuid>"}`
  - `{"type":"citations","content":[Citation...]}`
  - `{"type":"token","content":"..."}` (raw string chunks, repeated)
  - `{"type":"suggestedActions","content":["..."]}`
  - `{"type":"done"}`
  - `{"type":"error","content":"..."}`

---

## 3. Backend DTO shapes (exact, for type mapping)

Key schemas (from `backend/app/schemas/*.py`):

```
ModelSummary { id, tenant_id, user_id, name, type: ModelTypeEnum, description?, status?, created_at,
               current_version?: ModelVersionDTO }
ModelVersionDTO { id, model_id, version, is_current, parent_version_id?, metrics?: dict, gap_analysis?: dict, created_at }

DashboardMetricsResponse { active_models, documents_analyzed, compliance_issues }
TenantSettings { id, tenant_id, gini_tolerance, psi_warning_threshold, psi_breach_threshold,
                 auto_mask_bank, auto_mask_borrower, auto_mask_location, strict_zero_trust, updated_at }
NotificationResponse { id, title, description?, type: PASS|WARNING|BREACH|INFO, is_read, created_at, model_id? }
SearchResultItem { id, type: 'model'|'regulatory_standard', title, description? }
UserProfileResponse { id, email, full_name?, title?, division?, security_clearance?, role: RoleEnum, is_active, created_at }

RegulatoryStandardResponse { id, code, title, authority, jurisdiction, clauses_json: list[dict], created_at }
ComplianceGap { requirement, status, description, recommendation }
ComparisonDifference { category, description, doc_a_value, doc_b_value }
Citation { source, section, text, score, retrieval_method }

UploadResponse { document_id, filename, file_type, page_count, chunk_count, masking_report, metrics_summary }
DocumentMetadata { id, filename, file_type, upload_time, status, chunk_count }
```

### Enum values (serialized as their `str` value)
- `ModelTypeEnum`: `"PD"`, `"LGD"`, `"EAD"`, `"Credit Scoring"`, `"IFRS 9 ECL"`
- `ModelStatusEnum`: `"PASS"`, `"WARNING"`, `"BREACH"`
- `NotificationTypeEnum`: `"PASS"`, `"WARNING"`, `"BREACH"`, `"INFO"`
- `RoleEnum`: `"ANALYST"`, `"SENIOR_RISK_OFFICER"`, `"COMPLIANCE_AUDITOR"`, `"ADMIN"`
- `DocumentStatus`: `"PROCESSING"`, `"READY"`, `"ERROR"`

### Metrics/gap JSON stored on ModelVersion
`metrics` = `ModelValidationProfile.model_dump()` — each metric is `{value, unit, raw_text, context}` (e.g. `gini: {value: 63.4, unit: "%", ...}`).
`gap_analysis` = `BreachReport.model_dump()` — `{results: [{metric_name, value, threshold, status: PASS|WARNING|BREACH, rule_basis}]}`.

---

## 4. Compatibility mapping (UI type ← backend DTO)

Central work: an **adapter layer** (`src/lib/adapters.ts`) transforms backend DTOs into the UI `types.ts` shapes. Exact mapping below.

### 4.1 `ModelSummary` (UI) ← backend `ModelSummary` + `TenantSettings`
| UI field | Source |
|----------|--------|
| `id` | `id` |
| `name` | `name` |
| `type` | `type` (enum value, e.g. `"Credit Scoring"`) |
| `status` | `status ?? 'PASS'` |
| `version` | `current_version?.version` + label (e.g. `Version {v} • Production`) |
| `description` | `description ?? ''` |
| `lastAnalyzed` | relative-time format of `current_version?.created_at ?? created_at` |
| `portfolio` | **not in backend** → see gap G1 |
| `algorithm` | **not in backend** → see gap G1 |
| `metrics.{gini,auc,ks,psi}` | flatten `current_version.metrics.<key>.value` |
| `metrics.{giniThreshold,aucBenchmark,ksBenchmark,psiThreshold}` | from `TenantSettings` + defaults (see G6) |
| `gapAnalysis.requirements[]` | map each `current_version.gap_analysis.results[]` (see 4.2) |
| `gapAnalysis.overallCompliance` | computed client-side from requirements PASS/WARNING/BREACH ratio |

### 4.2 `ModelSummary.gapAnalysis` ← backend `BreachReport`
`PolicyResult {metric_name, value, threshold, status, rule_basis}` → requirement:
| UI field | Source |
|----------|--------|
| `id` | `req-{i}` (synthetic) |
| `title` | `metric_name` (humanized) |
| `icon` | derived from metric type (`database`, `model_training`, `timeline`, `description`, …) via a lookup map — **not in backend** |
| `status` | `status` (PASS/WARNING/BREACH); map BREACH → `'BREACH / GAP'` label if desired |
| `details` | `rule_basis` (+ `threshold`) |

`overallCompliance` = `round(pass + 0.5*warning) / total * 100` (mirrors the backend scoring convention).

### 4.3 `RegulatoryStandard` (UI) ← `RegulatoryStandardResponse`
| UI field | Source |
|----------|--------|
| `id`/`code`/`title`/`authority`/`jurisdiction` | direct |
| `effectiveDate` | **not in backend** → see G3 |
| `category` | **not in backend** → see G3 |
| `description` | **not in backend** → see G3 |
| `relevantClauses[]` | map `clauses_json[]` — backend clause objects currently store raw dicts; UI expects `{clause, topic, requirement, threshold}` → see G3 |

### 4.4 `RedactedEntity` (UI) ← `POST /privacy/mask` / `GET /privacy/redactions`
Backend returns `redactions: {rawString -> maskedPayload}` (dict, no type/timestamp). ADAPTER:
- `rawString` = key, `maskedPayload` = value
- `entityType` = derive from token prefix: `[BANK_`→`BANK`, `[PERSON_`→`PERSON`, `[LOC_`→`LOCATION`, `[ORG_`→`ORG`, else `IDENTIFIER` (see G7)
- `timestamp` = `new Date().toLocaleTimeString()` (client-side)
- `id` = index/masked token

### 4.5 `ChatMessage` (UI) ← `/query` SSE
- user message: local. AI message built from streamed `token` chunks.
- `sources[]` ← `citations` event: `{title: cite.source, ref: cite.section}`
- `suggestedActions[]` ← `suggestedActions` event
- `isHighlighted` → client-side flag (e.g. latest AI message)

### 4.6 `ComparisonModel` (UI) ← `/compare`
Backend is **document-level** and returns `{differences, summary}`. UI wants model-level baseline/challenger with `methodology/dataConfig/metrics/findings`. See G5. Adapter builds two `ComparisonModel` cards from current model + compared model metrics and maps `differences[]` into `dataConfigDiff`/`metrics` diffs.

### 4.7 Notifications (UI) ← `NotificationResponse`
| UI field | Source |
|----------|--------|
| `title` | `title` |
| `modelId` | `model_id` |
| `type` | `type` |
| `time` | relative time of `created_at` |

### 4.8 Lineage ← `GET /models/{id}/versions`
`ModelVersionDTO` lacks author/title/gini → derive:
- `version` = `version`, `isCurrent` = `is_current`
- `gini` = `metrics?.gini?.value` (if present)
- `status` = derive from `gap_analysis.results[]` or default
- `title`, `author` = **not in backend** → defaults (see G4)

### 4.9 Settings (UI) ← `TenantSettings`
Direct for `gini_tolerance`, `psi_warning_threshold`, `psi_breach_threshold`, `auto_mask_bank/borrower/location`, `strict_zero_trust`. UI also shows "observation months" → **not in backend** (see G6).

---

## 5. Gaps & decisions (adapter vs backend change)

| ID | Gap | Recommendation |
|----|-----|----------------|
| G1 | `Model` lacks `portfolio` & `algorithm` (needed by `ModelSummary` + `NewAuditModal`) | **Backend change (small)**: add `portfolio`, `algorithm` columns to `Model` + `ModelCreate`; wire into `POST /models`. Alternatively default client-side — but that loses real data. *Recommend backend.* |
| G2 | No ROC curve / population-deciles endpoints (`WorkspaceView` expects them) | **Locked (hybrid)**: ROC → synthesize client-side via binormal model from AUC (`Gini = 2·AUC − 1`); PSI deciles → parse document PSI table in backend (`model_metrics_extractor.py`) — not synthesized from the scalar. **No doc-chart image extraction.** |
| G3 | `RegulatoryStandard` lacks `effectiveDate`, `category`, `description`; clause field names differ | **Backend change (small)**: add the 3 columns + align clause JSON keys to `{clause, topic, requirement, threshold}`. Seed via a script (reference `REGULATORY_STANDARDS` is ideal seed data). |
| G4 | `ModelVersionDTO` lacks `author`/`title` | **Adapter**: derive `title` from `version`; default `author` from `UserProfile.me.full_name`. Optionally backfill author on version later. |
| G5 | `/compare` is document-level; UI is model-level | **Backend change (medium)**: add model-level compare (or map document ids). **Short-term**: adapter computes metrics diffs from the two models' `current_version.metrics`, and uses `/compare` on their latest documents for text findings. |
| G6 | `TenantSettings` lacks `min_observation_months` | **Backend change (small)**: add field. Otherwise hide/disable the control. |
| G7 | Redaction log has no entityType/timestamp; `redactions` is a dict | **Adapter** (see 4.4). No backend change needed. Optionally enrich backend later. |
| G8 | No `POST /notifications/{id}/read` | **Backend change (small)** OR client-only `is_read` stored in memory. Recommend add mark-read endpoint. |
| G9 | `/auth` has no UI in reference app | **Add** Login/Register view + token store + refresh-on-401 interceptor (required — backend is fully auth-gated). |
| G10 | Export: backend only returns JSON (`/export-data`) | **Client-side** generation with `jspdf` + `docx` (matches reference "client-side Blob" approach); JSON export = download `export-data`. |

**Recommendation summary:** Tier 1 backend work (G1, G3, G6, G8) is **done**. G2 is split: ROC is synthesized client-side (binormal, Phase E); PSI deciles are now parsed backend-side (`parse_population_deciles` + `GET /models/{id}/metrics/population-deciles`). G5 (model compare) backend endpoint (`POST /models/compare`) is done and the UI consumes it directly. The adapter layer hides the remaining mismatches.

---

## 6. Tech stack

| Item | Value |
|------|-------|
| Runtime | Node 20+, React 19 |
| Build | Vite 6 |
| TypeScript | ~5.8 |
| Styling | Tailwind CSS v4 via `@tailwindcss/vite` |
| Icons | `lucide-react` |
| Animation | `motion` (framer-motion successor) |
| Data fetching | native `fetch` in a small typed client (no hard dependency on axios/tanstack) |
| PDF/DOCX export | `jspdf` + `docx` (unit: client-side) |
| State | React context + custom hooks (no Redux needed) |

Port `index.css`, fonts (Inter / Plus Jakarta Sans / JetBrains Mono), and `assets/` from `modelaudit-ai/` for visual parity. Drop the reference app's extraneous deps (`express`, `@google/genai`, `dotenv`, `tsx`, `esbuild`).

---

## 7. Proposed file structure

```
frontend/
├─ package.json
├─ vite.config.ts            # react + tailwindcss plugins, @ alias, /api proxy -> :8001
├─ tsconfig.json
├─ index.html                # fonts, title, meta (ported)
├─ .env.example              # VITE_API_BASE_URL
└─ src/
   ├─ main.tsx
   ├─ index.css              # Tailwind v4 + theme tokens (ported + extended)
   ├─ App.tsx                # shell + nav state + layout (mirrors reference)
   ├─ types.ts               # ported reference types (source of truth)
   ├─ lib/
   │  ├─ http.ts             # fetch wrapper, auth header, 401->refresh, error normalization
   │  ├─ auth.ts             # token store, login/register/refresh
   │  ├─ api.ts              # typed endpoint functions (1:1 with §2)
   │  ├─ sse.ts              # POST+ReadableStream SSE parser for /query
   │  └─ adapters.ts         # §4 mapping (ModelSummary, gap, regulatory, redaction, chat, compare, lineage)
   ├─ hooks/
   │  ├─ useAuth.ts
   │  ├─ useModels.ts
   │  ├─ useDashboard.ts
   │  ├─ useSettings.ts
   │  ├─ useNotifications.ts
   │  └─ useChat.ts          # SSE stream consumption + session persistence
   ├─ data/fallback.ts       # binormal ROC synthesis + PSI threshold-gauge fallback (deciles until G2 parser ships)
   └─ components/
      ├─ TopNav.tsx  SideNav.tsx
      ├─ OverviewView.tsx  WorkspaceView.tsx  CompareModelsView.tsx
      ├─ RegulatoryLibraryView.tsx  SettingsView.tsx
      ├─ PrivacyInspectorDrawer.tsx  NotificationsDrawer.tsx
      ├─ NewAuditModal.tsx  ModelLineageModal.tsx  ExportReportModal.tsx
      ├─ ProfileModal.tsx  HelpModal.tsx
      └─ LoginView.tsx  RegisterView.tsx        # NEW (auth)
```

---

## 8. Data-flow architecture

1. **Auth**: on app load, read `access_token`/`refresh_token` from `localStorage`. If absent → render `LoginView`/`RegisterView`. On 401 → attempt `/auth/refresh`; if that fails → clear + show login.
2. **State**: top-level `AuthProvider`; per-view hooks fetch on mount and expose `{data, loading, error, refetch}`. `App.tsx` keeps `activeNav`, `currentModel`, modal/drawer open flags (mirror reference).
3. **SSE**: `useChat` opens `fetch('/query', {method:'POST', headers:{Authorization, 'Content-Type':'application/json'}, body})`, reads `res.body.getReader()`, buffers `data:` lines, `JSON.parse` each, routes by `type` (session_id/citations/token/suggestedActions/done/error). Note: **not** `EventSource` (that's GET-only) — use fetch streaming.
4. **Masked display**: all retrieved text (chunks, citations, compare output) is already masked server-side; the UI renders `masked_text`/masked tokens verbatim and surfaces `redactions` in the Privacy Inspector.

---

## 9. Implementation phases

**Phase A — Scaffold & theme**
- package.json (clean), vite.config, tsconfig, index.html, `@` alias, Tailwind v4, fonts, `index.css`, copy `assets/`. Acceptance: `npm run dev` renders reference-style shell skeleton.

**Phase B — Types, HTTP, auth**
- Port `types.ts`; add `methodologyDiff`/`dataConfigDiff` types. `lib/http.ts`, `lib/auth.ts`, `lib/api.ts`. `LoginView`/`RegisterView`. Decision on G1/G3/G6/G8 (backend pass) *before* finishing adapters. Acceptance: register→login→persist token→`GET /models` returns 200.

**Phase C — Adapters**
- Implement `lib/adapters.ts` per §4; unit-check against live responses. Acceptance: `ModelSummary` renders from real `GET /models` data.

**Phase D — Shell + Overview**
- `App.tsx`, `SideNav`, `TopNav`, `OverviewView` (dashboard metrics + model cards + search + status filter). Acceptance: matches reference look.

**Phase E — Workspace**
- Metrics dashboard, gap-analysis list, ROC chart (svg, binormal-synthesized from AUC), PSI deciles panel (PSI scalar vs warning/breach thresholds until G2 parser ships), citations tab. Acceptance: real model metrics + gaps render; ROC reconstructed from AUC; deciles show threshold gauge (no fabricated data).

**Phase F — AI Analyst chat (SSE)**
- `useChat` + chat UI; session_id reuse for multi-turn; sources + suggestedActions. Acceptance: stream works against `POST /query`.

**Phase G — Compare, Regulatory, Settings**
- `CompareModelsView` (adapter, G5), `RegulatoryLibraryView` (catalog + upload→analyze → `POST /documents/upload` then `/gap-analysis`), `SettingsView` (thresholds/toggles → `PUT /settings`).

**Phase H — Modals & drawers**
- NewAudit (create model → upload), Lineage, Notifications, Export (jspdf/docx/json), Privacy Inspector (list + live mask), Profile, Help.

**Phase I — Polish & hardening**
- Loading/empty/error states, egress-masked display, loading spinners, responsive/mobile nav, accessibility. 

**Phase J — Verify**
- `npm run build` (tsc + vite), `npm run lint`; smoke test against running backend (`uvicorn app.main:app --port 8001`): register → create model → upload PDF → view workspace → chat → compare → export.

---

## 10. Risks & open questions

1. **G5 (model compare) and G2-PSI (backend decile parser) backend work is done** (Tier 2: `POST /models/compare` + `GET /models/{id}/metrics/population-deciles`); G1/G3/G6/G8 are also done (Tier 1). Only G2-ROC remains client-side (Phase E binormal reconstruction).
2. **SSE contract is `data:`-only** (no named events); ensure the frontend parser matches `utils/streaming.py` exactly, and note `/query` yields raw strings *and* structured dicts mixed.
3. **`page_count` is always 0** in `UploadResponse` (backend stub) — UI should not surface a hardcoded 0 as truth; hide or mark "—".
4. **Masked-text everywhere**: citations/chunks are masked; the UI must not attempt to show original PII (except via Privacy Inspector redaction map).
5. **Enum → label** rendering (ModelType `IFRS 9 ECL` etc.) must be centralized to avoid drift.
6. **CORS/proxy**: dev via Vite proxy `/api → :8001`; prod via same-origin or `VITE_API_BASE_URL`. `ALLOWED_ORIGINS` already defaults to `:5173,:3000` (matches reference dev port 3000 — but Vite here defaults to 5173; align).
7. `openai` in venv reports version `3.6.0` (anomalous mirror version) — LLM-dependent features (chat/compare/gap) should be smoke-tested with a real API key, or gracefully degrade.

---

## 11. Backend prerequisite checklist (recommended, small)

- [x] G1: add `portfolio`, `algorithm` to `Model` + `ModelCreate` (+ migration).
- [x] G3: add `effective_date`, `category`, `description` to `RegulatoryStandard`; align `clauses_json` keys; seed catalog.
- [x] G6: add `min_observation_months` to `TenantSettings`.
- [x] G8: add `POST /notifications/{id}/read`.
- [x] G2-ROC: synthesized client-side via binormal model (no backend endpoint needed).
- [x] G2-PSI: parse PSI decile table in `model_metrics_extractor.py` → `GET /models/{id}/metrics/population-deciles`.
- [x] G5: model-level compare endpoint (`POST /models/compare`).

If these are deferred, the adapter layer handles all of them with defaults/placeholders, and no UI blocker remains.