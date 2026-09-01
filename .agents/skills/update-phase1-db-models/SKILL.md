---
name: update-phase1-db-models
description: Use this skill to execute Phase 1 of the ModelAudit AI Backend Extension Plan. This involves adding new SQLAlchemy models (Model, ModelVersion, TenantSettings, Notification, RegulatoryStandard, ChatSession, ChatMessage), updating the User model, and generating Alembic migrations.
---

# Phase 1: Database Foundation & Migrations

**Context:** The backend is shifting from a document-centric to a Model-centric architecture.

## Tasks
1. **Modify `backend/app/models.py` (or the respective module):**
   - Add `Model`: Core audit record (id, tenant_id, user_id, name, type, description, status, created_at).
   - Add `ModelVersion`: Lineage nodes (id, model_id, version, is_current, parent_version_id, created_at).
   - Add `TenantSettings`: Parameterized thresholds (id, tenant_id, gini_tolerance, psi_limits, auto_mask_toggles).
   - Add `Notification`: Alerts for users (id, tenant_id, user_id, model_id, title, description, type, is_read, created_at).
   - Add `RegulatoryStandard`: Migrated from hardcoded (id, code, title, authority, jurisdiction, clauses_json).
   - Add `ChatSession` & `ChatMessage`: Persisted conversation history for AI Analyst (session_id, user_id, model_version_id, created_at) and (id, session_id, role, content, sources_json).
   - Update `User`: Add profile fields (full_name, title, division, security_clearance).
2. **Generate Alembic Migration:**
   - Run `alembic revision --autogenerate -m "Add model-centric tables"` from the backend directory.
   - Run `alembic upgrade head` to apply it.

**Constraints:**
- Do NOT add a `RedactionLog` table. This must remain strictly in memory as per privacy rules.
- Ensure all models inherit from the declarative base and have proper foreign key relationships (e.g., `ModelVersion` belongs to `Model`, `Model` belongs to `Tenant`).
