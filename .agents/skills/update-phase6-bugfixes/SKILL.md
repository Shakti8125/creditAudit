---
name: update-phase6-bugfixes
description: Use this skill to execute Phase 6 of the ModelAudit AI Backend Extension Plan. This focuses on resolving final high-priority bugs and updating necessary dependencies.
---

# Phase 6: Final Bug-Fix Pass & Dependency Updates

**Context:** Several critical bugs and outdated dependencies were flagged in the backend code audit report and need fixing.

## Tasks
1. **Update Dependencies:**
   - Update `python-jose` to `PyJWT[crypto]` in `requirements.txt`.
   - Update `passlib` to `bcrypt>=4.1.0`.
   - Pin `pinecone-client>=5.0.0`.
   - Update the `Dockerfile` to include required Docling C-libraries (e.g., `libgl1`, `libglib2.0-0` or whatever is required by `DEP-03`).
2. **Fix Code-Level Bugs (`backend/app/core/` and others):**
   - Replace deprecated `datetime.utcnow()` with timezone-aware `datetime.now(timezone.utc)` across the entire codebase.
   - Fix the Reranker component so it does not drop 100% of candidates on an API error (implement fallback).
   - Locate and remove blocking synchronous I/O operations from within `async def` endpoints.
   - Ensure bare `except:` clauses are replaced with specific exception catching (at least `except Exception as e:` with logging).

**Constraints:**
- After updating dependencies, run the test suite to catch any immediate breaks caused by the updates (e.g., PyJWT has a different API than python-jose).
