---
name: update-phase5-chat-privacy
description: Use this skill to execute Phase 5 of the ModelAudit AI Backend Extension Plan. This focuses on chat session persistence and in-memory privacy inspection features.
---

# Phase 5: AI Analyst Chat & Privacy Endpoints

**Context:** The UI needs a persistent chat experience and a way to view live redactions without violating zero-trust storage rules.

## Tasks
1. **Enhance Chat (`backend/app/api/query.py`):**
   - Accept a `session_id`. If none provided, create a new `ChatSession` linked to the user and `ModelVersion`.
   - Persist user queries and the final AI responses into the `ChatMessage` table.
   - Inject chat history into the LLM context.
   - Add `suggestedActions` to the streaming response payload (SSE).
2. **Implement Privacy Endpoints (`backend/app/api/privacy.py`):**
   - `GET /privacy/redactions`: Return the redaction log from the *in-memory* `EntityRegistry` for the current user's session.
   - `POST /privacy/mask`: Create a live redaction simulator endpoint that runs text through the `MaskingPipeline` and returns the masked payload.

**Constraints:**
- The `EntityRegistry` used for `/privacy/redactions` MUST NOT be persisted to the database. It must remain in server memory (or Redis, if configured strictly for session TTL, but memory is preferred for absolute zero-trust).
- Ensure SSE streaming formats remain intact when adding `suggestedActions`.
