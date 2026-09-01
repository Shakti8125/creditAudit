# ModelAudit AI — Pending Backend Changes (Tier 2 & Tier 3)

Status of frontend-compat gaps after Tier 1 is implemented. Tier 1 = small backend additions being done now (G1, G3, G6, G8). This document records the **deferred** and **adapter-owned** work so it is not lost.

---

## Tier 2 — Analytic features (approach locked 2026-08-30)

T2-1 remains frontend work (Phase E). The backend halves of T2-2 and T2-3 are now **implemented** (verified 2026-08-30). **Agreed: no document-chart image extraction** — figure crops add latency, are not privacy-masked, and recovering data series from a chart image would require deplot/vision models. That path is out of scope for now.

### T2-1 — ROC curve (gap G2) — **DECIDED: synthesize client-side**
- **Approach:** reconstruct a smooth ROC from the extracted AUC using the **binormal model**. The extracted metrics are self-consistent (`Gini = 2·AUC − 1`), and AUC unambiguously parameterizes the curve.
- **Why not backend:** the pipeline records AUC as a scalar (no per-threshold TPR/FPR), and a binormal reconstruction is a legitimate approximation with zero extra cost or latency.
- **Frontend implementation:** pure function `auc → {fpr, tpr}[]` in the lib layer, rendered as SVG and labeled *"reconstructed from AUC"*.

### T2-2 — Population stability deciles (gap G2) — **DONE (backend)**
- **Approach:** recover actual deciles from the document's PSI **table**, which Docling already extracts to markdown (PSI expected/actual is almost always tabular).
- **Why not synthesize:** PSI is a single scalar; the decile distribution is underdetermined — back-mapping would be fabrication, not approximation.
- **Backend (implemented):** `parse_population_deciles()` in `app/services/analytics/model_metrics_extractor.py`; persisted to `ModelVersion.population_deciles` during upload (`api/documents.py`); exposed via `GET /models/{id}/metrics/population-deciles` (`PopulationDecilesResponse`). Migration: `alembic/versions/c7d8e9f0a1b2_add_population_deciles.py`.
- **Frontend consumption (Phase E):** render the parsed deciles in the Workspace PSI panel.

### T2-3 — Model-level compare endpoint (gap G5) — **DONE (backend)**
- **Need:** compare two *models* (baseline vs challenger) producing `{methodology/dataConfig, metrics{diff}, findings}` — not the document-level `/compare`.
- **Backend (implemented):** `POST /models/compare` (`ModelCompareRequest {model_id_a, model_id_b}` → `ModelCompareResponse`) in `api/models.py`; DTOs `ComparisonModelDTO`, `ComparisonMetric`, `ComparisonDiff`, `ComparisonFindings` in `schemas/compare.py`.
- **Frontend consumption (Phase G):** `CompareModelsView` calls this endpoint directly; the metrics-diff adapter is now only a fallback.

---

## Tier 3 — Adapter-only / frontend-owned (no backend change required)

These are resolved entirely in the frontend adapter layer (`frontend/src/lib/adapters.ts`).

### T3-1 — Lineage `author` / `title` (gap G4)
- `GET /models/{id}/versions` returns `ModelVersionDTO` with no `author`/`title`.
- Frontend: `title` = `version` label; `author` = `"—"` (or enrich later by joining `Model.user_id` → `User.full_name`, which requires a backend change and is out of scope).

### T3-2 — Redaction `entityType` / `timestamp` (gap G7)
- `POST /privacy/mask` and `GET /privacy/redactions` return `redactions: {rawString → maskedPayload}` (a dict, no type/timestamp).
- Frontend derives:
  - `entityType` from token prefix: `[BANK_` → `BANK`, `[PERSON_` → `PERSON`, `[LOC_`/`[LOCATION_` → `LOCATION`, `[ORG_` → `ORG`, else `IDENTIFIER`.
  - `timestamp` = `new Date().toLocaleTimeString()`.
  - `id` = index or masked token.

### T3-3 — Auth UI (gap G9)
- Backend is fully JWT-gated (`HTTPBearer` on all `/models|/documents|/system|/query|/privacy|/compare|/gap-analysis|/regulatory` routes).
- Frontend owns: `LoginView`/`RegisterView`, token storage (`localStorage`), `Authorization: Bearer` header, and refresh-on-401 via `POST /auth/refresh`.

### T3-4 — Export report (gap G10)
- Backend only exposes JSON via `GET /models/{id}/export-data`.
- Frontend owns: PDF/DOCX generation with `jspdf`/`docx` (mirrors reference "client-side Blob"), JSON = download `export-data`; `includeCitations`/`includeAuditTrail` are client-side toggles.

### T3-5 — Masked-model data rendering (implicit)
- All retrieved text (chunks, citations, compare/gap output) is already masked server-side. Frontend renders masked tokens verbatim; original PII is surfaced only through the Privacy Inspector redaction map.
- `UploadResponse.page_count` is always `0` (backend stub) — frontend must render `"—"` rather than `0`.

---

## Carry-over risk notes (not directly T2/T3, but relevant)

- `regulatory_standards` table was previously **unseeded**; Tier 1 adds a seed script (`scripts/seed_regulatory_standards.py`) using the reference catalog.
- `openai` in the venv reports version `3.6.0` (anomalous mirror version) — LLM-backed endpoints (chat/compare/gap) need smoke testing with real keys.
- Vite dev port default is `5173`; backend `ALLOWED_ORIGINS` default covers `:5173,:3000`. Align dev port or proxy `/api → :8001`.

## When to revisit
- **T2-1 (ROC synthesis)** lands with the frontend Workspace (Phase E) — client-side binormal reconstruction; no backend needed.
- **Doc-chart images:** only if a reviewer explicitly needs to view the original chart; would be a separate, privacy-reviewed "source document viewer" feature.