---
name: update-phase2-model-apis
description: Use this skill to execute Phase 2 of the ModelAudit AI Backend Extension Plan. This involves building CRUD operations for Models, aligning Pydantic schemas with UI types, and fixing auth handler bugs.
---

# Phase 2: Core Model APIs & Schema Alignment

**Context:** The frontend UI relies on a set of endpoints to list and manage Models and their versions.

## Tasks
1. **Fix Auth Handlers (`backend/app/api/deps.py` or similar):**
   - Resolve `TokenPayload` `.get()` misuse (`AttributeError`) in auth-gated handlers. Ensure standard attribute access or dict methods are used correctly.
2. **Align Schemas (`backend/app/schemas/`):**
   - Create Pydantic models aligning with UI interfaces: `ModelSummary`, `ModelVersionDTO`, `ModelExportData`.
   - Update existing schemas to fix `Pydantic v2` `ConfigDict` deprecation warnings.
3. **Build Model Routes (`backend/app/api/models.py`):**
   - `GET /models`: List tenant-scoped models.
   - `POST /models`: Create a new Model and an initial `ModelVersion`.
   - `GET /models/{id}`: Get full summary including metrics and gap analysis (fetching from the latest ModelVersion).
   - `GET /models/{id}/versions`: Get model lineage history.
   - `GET /models/{id}/export-data`: Comprehensive JSON payload of the model's data for frontend PDF/DOCX generation.
4. **Register Router:**
   - Include the new router in `backend/app/main.py` or the API router registry.

**Constraints:**
- All endpoints must verify the `tenant_id` from the JWT token for multi-tenancy.
- Ensure async operations (`async def`) and use the injected DB session.
