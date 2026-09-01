# ModelAudit AI — Backend Update Plan

Goal: extend the existing backend so it fully supports the functionality of the reference UI
(`modelaudit-ai/`). This plan maps every UI feature to either an existing backend capability
or a new endpoint/model/service that must be built. It does **not** contain code changes.

## 1. Reference UI feature inventory → backend needs

The reference UI has 5 top-level views + 8 modals/drawers. Below is the mapping.

### 1.1 Overview View (landing dashboard)
| UI need | Backend status | Action |
|---|---|---|
| List of audited models (`ModelSummary[]`) w/ name, version, algorithm, type, lastAnalyzed, status | **No `Model` entity exists** — backend only has `Document`/`User`/`Tenant` | Build a `Model` model + `GET /models` |
| Headline stats (Active Models, Documents Analyzed, Compliance Issues, AI Reviews) | No aggregated metrics endpoint | Build `GET /dashboard/metrics` |
| Filter by status / search | Client-side only | Optional server-side query params |

### 1.2 Workspace View (Performance & Gap Dashboard + Document/AI Analyst)
The single densest screen.
| UI need | Backend status | Action |
|---|---|---|
| Model metrics (gini/auc/ks/psi + thresholds/benchmarks) | `ModelValidationProfile` schema exists (Optional MetricValue) but is only nested inside upload response, not persisted per-model, and uses `MetricValue{value,unit,raw_text,context}` | Persist metrics on `Model`; add `GET /models/{id}` returning the `ModelSummary`-shaped DTO |
| Gap analysis (overallCompliance % + requirements[] with PASS/WARNING/BREACH) | `POST /gap-analysis` exists → returns `{gaps, coverage_score}` (LLM-only), **not persisted**, shape differs (`ComplianceGap` vs UI `requirements[]`) | Persist gap results; add `GET /models/{id}/gap-analysis`; align the required shape (id, title, icon, status, details) |
| ROC curve data (fpr/tpr points) | Not present (UI has `ROC_CURVE_DATA` mock) | Add `GET /models/{id}/metrics/roc` |
| PSI decile distribution (decile, expected, actual) | Not present (UI `POPULATION_DECILES_DATA` mock) | Add `GET /models/{id}/metrics/population-deciles` |
| AI Analyst chat (SSE) w/ sources & suggestedActions | `POST /query` SSE exists but returns citations+token stream, no `session_id` persistence, no conversation memory, no `suggestedActions` | Extend query to accept/return conversation metadata; add session handling |
| Document viewer content (page text, page count, flag spans) | `GET /documents/{id}` returns masked chunks | Add endpoint (or extend) to expose browsable page text + flagged findings |

### 1.3 Compare Models View
| UI need | Backend status | Action |
|---|---|---|
| baseline vs challenger diff (methodology/dataConfig/metrics/findings with added/changed/removed) | `POST /compare` exists (doc-to-doc, LLM JSON diff) but **operates on documents, not models**, and shape differs (`ComparisonDifference` vs UI `ComparisonModel`) | Build model-level compare; add model-version concepts; align DTO |

### 1.4 Regulatory Library View
| UI need | Backend status | Action |
|---|---|---|
| List `RegulatoryStandard[]` (code, authority, jurisdiction, clauses) | `POST /regulatory/search` exists (single QA RAG); **no list endpoint**; corpus hardcoded 10 sections in `hybrid_retriever.py` | Add `GET /regulatory/standards` returning the catalog (matched to UI field names) |
| Document upload + analyze (progress + PII scrub) | `POST /documents/upload` exists (Docling→metrics→policy→EWS→mask→chunk) but embeddings mocked, no progress/job status, no analysis result surfaced to model | Surface processing status; wire real Pinecone upsert; return analysis summary in UI shape |

### 1.5 Settings View
| UI need | Backend status | Action |
|---|---|---|
| Thresholds + zero-trust toggles (giniTolerance, psi thresholds, observation months, auto-mask bank/borrower/location, strict zero-trust) | **Not persisted anywhere** | Add `TenantSettings` model + `GET /settings` + `PUT /settings` |
| These should feed PolicyChecker/thresholds | Thresholds hardcoded in `policy_checker.py` | Parameterize thresholds from tenant settings |

### 1.6 New Audit Modal
| UI need | Backend status | Action |
|---|---|---|
| Create an audit: modelName, modelType, algorithm, portfolio, description + document upload | **No model creation endpoint** | Build `POST /models` (creates `Model` + optionally links uploaded document, runs pipeline) |

### 1.7 Model Lineage Modal
| UI need | Backend status | Action |
|---|---|---|
| Version genealogy (version, title, author, status, gini, isCurrent) | **Does not exist** | Add `ModelVersion` model + `GET /models/{id}/lineage` |

### 1.8 Export Report Modal
| UI need | Backend status | Action |
|---|---|---|
| Export report (pdf/docx/json + includeCitations + includeAuditTrail) | **Does not exist** (UI does client-side Blob) | Add `POST /models/{id}/export` returning a generated file/URL |

### 1.9 Privacy Inspector Drawer
| UI need | Backend status | Action |
|---|---|---|
| Redaction entity log (`RedactedEntity[]` rawString/maskedPayload/entityType/timestamp) | `EntityRegistry` + `MaskingPipeline` exist but registry is **in-memory/session-scoped, not persisted** | Persist a redaction log; add `GET /privacy/redactions` |
| Live redaction simulator (`POST /privacy/mask`) | MaskingPipeline exists | Expose `POST /privacy/mask` (returns masked payload + entity types) |

### 1.10 Notifications Drawer
| UI need | Backend status | Action |
|---|---|---|
| Alert list (title, modelId, type warning/pass/breach, time) | **Does not exist** | Add `Notification` model + `GET /notifications` (populate from EWS/policy/gap results) |

### 1.11 Profile Modal
| UI need | Backend status | Action |
|---|---|---|
| Validator profile (role, division, clearance, accreditation) | `User` model has role but no profile fields | Extend `User` (or add profile) + `GET /users/me` |

### 1.12 TopNav / SideNav (system)
| UI need | Backend status | Action |
|---|---|---|
| Global search (audits/metrics/clauses) | No search endpoint | Add `GET /search?q=` |
| Storage usage widget | Static | Add `GET /system/storage` |

---

## 2. New data models to add (Alembic migration)

1. **`Model`** — core audit record tying to `Tenant` + `User`:
   - id (UUID), tenant_id, user_id, name, type (enum: PD, LGD, EAD, Credit Scoring, IFRS 9 ECL), portfolio, algorithm, description, version, status (PASS/WARNING/BREACH), last_analyzed, created_at.
2. **`ModelMetrics`** (or JSON column on Model) — gini, giniThreshold, auc, aucBenchmark, ks, ksBenchmark, psi, psiThreshold (+ ROC points, deciles).
3. **`GapAnalysisRequirement`** (or JSON) — id, title, icon, status, details; plus overall_compliance on Model.
4. **`ModelVersion`** — lineage nodes: version, title, author, status, gini, is_current, parent_id.
5. **`TenantSettings`** — threshold/toggle JSON (giniTolerance, psi_warning, psi_breach, min_observation_months, auto_mask_bank/borrower/location, strict_zero_trust).
6. **`Notification`** — id, tenant_id, user_id, model_id, title, description, type (warning/pass/breach), is_read, created_at.
7. **`RedactionLog`** — id, tenant_id, document_id/model_id, raw_string, masked_payload, entity_type, created_at.
8. Extended **`User`** profile fields — full_name, title, division, security_clearance, accreditation.

---

## 3. New / modified API endpoints

### New (models domain) — `app/api/models.py`
- `GET /models` — list (tenant-scoped) → `ModelSummary[]`
- `POST /models` — create audit → `ModelSummary`
- `GET /models/{id}` — full summary (metrics + gap analysis)
- `GET /models/{id}/metrics/roc` — ROC curve points
- `GET /models/{id}/metrics/population-deciles` — PSI deciles
- `GET /models/{id}/gap-analysis` — requirements + compliance
- `GET /models/{id}/lineage` — version history
- `POST /models/{id}/export` — report file (pdf/docx/json)
- `POST /models/{id}/chat` — (or reuse `/query`) AI analyst with session/sources/suggestedActions

### New (system/domain) 
- `GET /dashboard/metrics` — headline institutional stats
- `GET /regulatory/standards` — regulatory catalog (list)
- `GET /notifications` + `POST /notifications/{id}/read`
- `GET /privacy/redactions` + `POST /privacy/mask`
- `GET /settings` + `PUT /settings`
- `GET /users/me` (profile)
- `GET /search?q=` (global search)
- `GET /system/storage`

### Modified existing
- `POST /documents/upload` — real Pinecone upsert (un-mock embeddings), real `page_count` + `chunk_count`, return analysis in UI shape, persist redaction log.
- `POST /gap-analysis` — persist results to `Model`, align response shape to UI `requirements[]`.
- `POST /query` — persist `session_id`, return `suggestedActions`, integrate NeMo guardrails (currently bypassed).
- Config: rate limiter tier actually read from token (currently always FREE).

---

## 4. Critical existing bugs that block the UI (from audit — fix as part of this work)

These were identified in `backend_code_audit_report.md` (120 findings) and are prerequisites for a working UI integration:

### 4.1 Blockers
- `TokenPayload` `.get()` misuse — `AttributeError` in all 5 auth-gated handlers.
- Embeddings are mocked → dense/Pinecone retrieval silently returns nothing (UI chat fallback to BM25 only; comparisons/regulatory degrade).
- Pinecone CBUAE namespace never seeded (only in-memory BM25 works).
- No Alembic `versions/` migration files — DB tables won't materialize.

### 4.2 High priority
- Unbounded file-upload memory (DoS).
- Missing chunk overlap in chunker.
- `datetime.utcnow()` deprecated; bare `except` swallowing.
- Reranker drops 100% candidates on API error.
- Blocking sync I/O inside async endpoints.
- `chunk_count`/`page_count` hardcoded 0.
- `Pydantic v2` `ConfigDict` and `declarative_base()` cleanup.

### 4.3 Dependencies to fix (from audit §3)
- `python-jose` → `PyJWT[crypto]`
- `passlib` → `bcrypt>=4.1.0`
- `pinecone-client` → `pinecone>=5.0.0`
- Dockerfile missing Docling C-libraries (`DEP-03`).

---

## 5. Implementation phases (recommended order)

**Phase A — Data & migrations foundation**
- Add `models.py` models (Model, ModelVersion, TenantSettings, Notification, RedactionLog), User profile fields.
- Generate Alembic migration (`alembic revision --autogenerate`).

**Phase B — Models domain API**
- `app/api/models.py` + schemas: list/create/get/metrics/roc/deciles/gap-analysis/lineage/export.

**Phase C — System API**
- dashboard, notifications, privacy mask/redactions, settings, search, users/me, storage.

**Phase D — Persistence wiring**
- Link document upload → Model; persist metrics, gap results, redaction log; real Pinecone upsert.

**Phase E — Streaming/chat/session improvements**
- session memory, suggestedActions, NeMo guardrails integration in query path.

**Phase F — Bug-fix pass**
- Resolve §4 blockers/high-priority/dependencies before accepting the integration.

**Phase G — Regulatory catalog**
- `GET /regulatory/standards` serving the catalog with UI field names.

---

## 6. Field-shape alignment notes (UI `types.ts` ↔ backend DTOs)

The UI `types.ts` is the source of truth for DTOs. Key mappings to preserve **exact** names:
- `ModelSummary.metrics` → flat numbers + thresholds (`gini`, `giniThreshold`, `auc`, `aucBenchmark`, `ks`, `ksBenchmark`, `psi`, `psiThreshold`) — note: this is **different** from backend `MetricValue{value,unit,raw_text,context}`. Recommend new response schemas for model APIs rather than repurposing `ModelValidationProfile`.
- `ModelSummary.gapAnalysis` → `{overallCompliance, requirements[{id,title,icon,status,details}]}` — differs from `gap_analysis.ComplianceGap{requirement,status,description,recommendation}`. Add `icon` + map `description`→`details`.
- `ComparisonModel` (title, role, version, methodology[+Diff], dataConfig[+Diff], metrics[{name,value,oldValue,newValue,isDiff}], findings) differs from `CompareResponse.differences[]`. Add model-level compare DTOs.
- `RegulatoryStandard` (code, title, authority, jurisdiction, effectiveDate, category, description, relevantClauses[{clause,topic,requirement,threshold}]) — new catalog schema needed.
- `RedactedEntity` (rawString, maskedPayload, entityType, timestamp) — new schema; map from RedactionLog.

---

## 7. Summary of work by size

| Category | Items | Effort |
|---|---|---|
| New API endpoints | ~18 new | Large |
| New DB models (+ migration) | 8 models | Large |
| Streaming/chat/session | 1 extension | Medium |
| Persistence wiring (upload→model, metrics, gaps, redactions, pinecone) | 1 major rework | Large |
| Regulatory catalog | 1 endpoint | Small |
| Settings → parameterized thresholds | 1 rework | Medium |
| Critical bug fixes (blockers + high + deps) | ~12 items | Large |
| DTO shape alignment | 6 schema groups | Medium |

**Note**: The backend currently implements a document-centric RAG + analytics engine but has **no `Model`/audit concept**, which is the central object of the reference UI. Adding the `Model` domain and persisting analytics results to it is the largest conceptual gap; the existing privacy/retrieval/LLM/analytics services are largely reusable as-is once the bugs are fixed and their outputs are persisted/surfaced.