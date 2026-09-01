---
name: update-phase3-system-apis
description: Use this skill to execute Phase 3 of the ModelAudit AI Backend Extension Plan. This involves building endpoints for system features like dashboard metrics, tenant settings, global search, and regulatory standards.
---

# Phase 3: System, Regulatory, and Search APIs

**Context:** The UI requires a variety of system-level data points and dynamic settings.

## Tasks
1. **Create `backend/app/api/system.py`:**
   - `GET /dashboard/metrics`: Calculate aggregated stats (Active Models, Documents Analyzed, Compliance Issues) across the tenant's models.
   - `GET /settings` and `PUT /settings`: Manage the `TenantSettings` row.
   - `GET /notifications`: Fetch user alerts from the `Notification` table.
   - `GET /search?q=`: Basic `ILIKE` search over `Model.name`, `Model.description`, and `RegulatoryStandard.title`.
   - `GET /users/me`: Return extended user profile fields.
2. **Create `backend/app/api/regulatory.py`:**
   - `GET /regulatory/standards`: Fetch the catalog of standards from the new `RegulatoryStandard` DB table.
3. **Register Routers:**
   - Include these routers in the main application.

**Constraints:**
- Maintain strict multi-tenancy (`tenant_id` filtering on all queries).
- Update `PolicyChecker` to use the parameterized `TenantSettings` instead of hardcoded values, if possible in this phase (or prepare the hook for it).
