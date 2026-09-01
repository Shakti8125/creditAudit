---
name: update-phase4-pipeline-wiring
description: Use this skill to execute Phase 4 of the ModelAudit AI Backend Extension Plan. This focuses on wiring the document upload and analytics pipeline to persist results to the new ModelVersion entity, and fixing chunker/vector DB bugs.
---

# Phase 4: Persistence Wiring & Upload Pipeline Updates

**Context:** The original pipeline returned transient results. It now needs to persist everything to the database linked to a `ModelVersion`.

## Tasks
1. **Refactor Upload Pipeline (`backend/app/api/documents.py` or similar):**
   - Accept a `model_version_id` parameter (or determine it based on the upload context).
   - After extraction, metric calculation, and gap analysis:
     - Persist the documents to the `ModelVersion`.
     - Persist metrics and gap analysis results to the `ModelVersion`.
2. **Fix Vector Store & Chunking Bugs:**
   - Wire the real Pinecone upsert (remove any mock embeddings).
   - Ensure the Pinecone namespace includes the `tenant_id` properly.
   - Fix missing chunk overlap in the document chunker logic.
3. **Fix Upload Resource Leaks:**
   - Resolve unbounded file-upload memory issues (e.g., use SpooledTemporaryFile or stream to disk).

**Constraints:**
- Ensure all masking and privacy checks happen *before* upserting to Pinecone.
- The pipeline might be synchronous or background; ensure database sessions are handled correctly.
