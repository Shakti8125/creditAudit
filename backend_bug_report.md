# ModelAudit AI — Backend Bug Report

Date: 2026-08-30
Scope: audit of `backend/` against `backend_gap_plan.md` plus a full code/API/service/dependency review.

Summary: no crash-on-import bug was observed once `pinecone` is correctly installed, but several items silently degrade core behavior (vector retrieval, dense embeddings) or are dead code. The `.get()` TokenPayload misuse bug identified in the earlier audit is **already fixed** in this revision.

---

## Severity legend

- **BLOCKER** — breaks runtime or silently disables a core feature
- **HIGH** — data loss / silent degradation / correctness
- **MEDIUM** — fragility, drift, incomplete behavior
- **LOW** — cosmetic / maintainability

---

## BLOCKER

| ID | Location | Issue | Fix |
|----|----------|-------|-----|
| B1 | `app/services/retrieval/pinecone_store.py:8-13` | Installed package is legacy `pinecone-client 6.0.0`, whose `__init__` **raises** on import. The `try/except` swallows it and sets `Pinecone = None`, so every vector upsert/query silently no-ops. `requirements.txt:41` pins `pinecone>=5.0.0` but the venv was never re-synced. | Uninstall `pinecone-client`/`pinecone-plugin-interface`, install `pinecone>=5.0.0`. |
| B2 | `app/services/llm/gemini_provider.py:96` | `types.TaskType.RETRIEVAL_QUERY/RETRIEVAL_DOCUMENT` — `types.TaskType` does **not** exist in `google-genai 2.20.0` (verified). `embed()` raises `AttributeError`; `DenseRetriever` swallows it → dense/Pinecone retrieval returns nothing. | Pass plain string: `task_type = "RETRIEVAL_QUERY" if input_type == "query" else "RETRIEVAL_DOCUMENT"` (`EmbedContentConfig.task_type` is a string field). |
| B3 | `requirements.txt:27` vs env | `openai>=1.40.0` pinned, installed `openai 3.5.0`. `AsyncOpenAI`/`RateLimitError`/`APIError` all present (verified), so imports succeed, but versions drift and semantics may differ. | Install a real `openai>=1.40.0`. |
| B4 | `requirements.txt:21` vs env | `bcrypt>=4.1.0` pinned, installed `bcrypt 3.2.2`; stale `passlib`/`python-jose` still present. | Uninstall `python-jose`/`passlib`, install `bcrypt>=4.1.0`. |
| B5 | `tests/adversarial_deep_stress_harness.py:263-264` | Constructs `Notification(..., message=...)` but the model column is `description`, not `message` (`app/models/system.py`). Raises `TypeError` at test setup. | Change `message=` to `description=`. |

---

## HIGH

| ID | Location | Issue | Fix |
|----|----------|-------|-----|
| H1 | `app/api/documents.py:170-189` | Computes `compliance_score` then writes `parent_model.compliance_score` — but `Model` (and the migration) have **no** `compliance_score` column. `hasattr` guard makes it a silent no-op; the score is never persisted. Dashboard uses `status`, not the score. | Remove the dead computation + write (status computation is already independent). |
| H2 | `app/models/audit.py:40`, `app/models/system.py:53` | Columns named `type` (reserved keyword in PostgreSQL). SQLAlchemy auto-quotes so it works on Postgres/SQLite, but raw SQL/tooling won't. Rename DB column (keep Python attribute) via `mapped_column("model_type", ...)` / `mapped_column("notification_type", ...)`. | Use explicit column names; keep DTO field `type` unchanged. |
| H3 | `app/services/guardrails/config.yml` + `rails.co` | `nvidia_ai_endpoints` engine has no wired API key (every query silently blocked); `mask pii entities` and `check prompt injection` flows are `return` stubs (do nothing). | Wire `NVIDIA_API_KEY` via RailsConfig; implement/remove stub rails. |
| H4 | `.env.example` missing | Redis/NVIDIA/Gemini/Pinecone/JWT settings undocumented; rate-limiter/guardrails/vector fail-open silently in fresh envs. | Create `.env.example`. |
| H5 | `deploy/`/Dockerfile | Docling C-libs incomplete (`libgl1 libglib2.0-0 libgomp1` only; missing OpenCV/X11/`tesseract-ocr`), Python 3.12 image vs 3.13 venv. | Add missing libs; align Python. |

---

## MEDIUM

| ID | Location | Issue | Fix |
|----|----------|-------|-----|
| M1 | `app/services/chunker.py:46-50,71-74` | Final fallback hard-splits oversized text with **no overlap**; `len(raw_parts) <= 1` early-return can emit a single chunk larger than `chunk_size`. | Split remainder into ≤`chunk_size` pieces with overlap. |
| M2 | `app/api/__init__.py` | Does not export `models`/`system` routers (imported directly in `main.py`). | Add to imports + `__all__`. |
| M3 | `app/services/privacy/egress_validator.py:84` | Leak re-check covers only `ORG/PERSON/EMAIL/PHONE/GPE`; misses other token categories. | Extend category tuple. |
| M4 | `app/services/document_extractor.py` | Upstream `BinaryIO` is not `seek(0)`-ed before conversion. | Rewind stream. |
| M5 | `app/config.py` | `allowed_origins` read as raw string; `rate_limits` ignores env. | Parse to list; wire env. |
| M6 | `tests/services/test_guardrails.py` | Hits real NeMo runtime (`GuardrailsService()`); `test_guardrails_jailbreak` is a `pass` no-op. | Unit-test without network; implement jailbreak test or drop stub. |
| M7 | `alembic/env.py` | Imports only 4 models; relies on `app/models/__init__` to register the rest (works, but fragile). | Import all models explicitly. |

---

## LOW

| ID | Location | Issue |
|----|----------|------|
| L1 | `services/{chunking,extraction,vector}/` | Duplicate shim packages re-export from `services/` — drift hazard (currently consistent). |
| L2 | `utils/security.py:85,98` vs `TokenPayload` | JWT `sub` is string; `TokenPayload.sub` typed `uuid.UUID` (coerced in `deps.py`) — semantic mismatch only. |
| L3 | `schemas/auth.py` | `EmailStr` requires `email-validator` (verify it is installed). |
| L4 | enum name/value skew | `ChatRoleEnum`/`ModelTypeEnum` persist enum **names** (`USER`, `CREDIT_SCORING`) not `.value` (`user`, `Credit Scoring`) — consistent today, but a latent foot-gun (consider `values_callable`). |
| L5 | `main.py:38` | `allowed_origins` fallback hard-coded in two places (also `config.py`) — drift-prone. |

---

## Previously-identified audit items — status

| Item | Status |
|------|--------|
| `TokenPayload .get()` misuse (`AttributeError`) | ✅ Fixed — all auth-gated handlers use attribute access; `rate_limiter.py` branches on `isinstance(current_user, TokenPayload)`. |
| Reranker drops 100% on API error | ✅ Fixed — falls back to top-N input candidates. |
| 8 missing DB models | ✅ Added & imported in `models/__init__.py`; migration covers all tables. |
| `python-jose` → `PyJWT[crypto]` | ✅ In code + `requirements.txt` (stale package still in venv → see B4). |
| `passlib` → `bcrypt>=4.1.0` | ✅ In code + `requirements.txt` (stale `passlib` in venv → see B4). |
| Mocked embeddings / Pinecone silent failure | ❌ See B1 / B2. |
| Alembic migration missing | ✅ Present: `alembic/versions/0e6c2385a516_add_model_centric_tables.py`. |

---

## Recommended fix order

1. Re-sync venv (B1/B3/B4).
2. `gemini_provider.py` TaskType (B2).
3. Remove dead `compliance_score` (H1).
4. Reserve-word-safe column names (H2) + `.env.example` (H4) + guardrails wiring (H3).
5. Chunker overlap (M1), router exports (M2), Dockerfile libs (H5).