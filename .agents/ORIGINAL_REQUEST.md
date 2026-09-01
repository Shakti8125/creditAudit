# Original User Request

## 2026-08-28T13:31:16Z

Comprehensive code audit of the ModelAudit AI Python/FastAPI backend (~50 source files across 7 modules). The team should review the existing codebase for bugs, broken imports, API misuse, and correctness issues — producing a detailed bug report. No code changes should be made. The team may use web search to verify current library API signatures and documentation. Skip the frontend (`frontend/`) and deployment (`deploy/`) directories entirely.

Working directory: c:\Users\Shakti\Documents\CreditAudit- AI
Integrity mode: development

## Requirements

### R1. Static Code Review Across All Backend Modules

Review every Python file under `backend/app/` for the following categories of bugs:

- **Broken imports and missing dependencies**: Imports that reference nonexistent modules, wrong package names, or packages not in `requirements.txt`
- **Incorrect API usage vs. latest library docs**: Verify method signatures, class hierarchies, and configuration patterns against current versions of: Pydantic v2 (not v1 patterns), SQLAlchemy 2.0 async, FastAPI 0.112+, spaCy 3.7+, Presidio (analyzer/anonymizer), Pinecone (pinecone-client), NeMo Guardrails 0.11+ (Colang 2.0), google-genai SDK, openai SDK 1.40+, upstash-redis, python-jose, passlib/bcrypt
- **Type annotation correctness**: Missing or incorrect type hints, incompatible types, wrong generic parameters
- **Async/await correctness**: Missing awaits on coroutines, blocking sync calls inside async functions, improper event loop usage
- **Security issues**: JWT validation gaps, SQL injection risk, path traversal in file uploads, exposed secrets, CORS misconfiguration
- **Privacy pipeline logic**: Verify the masking/unmasking flow (entity_registry → bank_matcher → ner_masker → masking_pipeline → egress_validator) for correctness — tokens must never leak real entity names to LLM providers

### R2. Dependency Compatibility Check

Review `backend/requirements.txt` for:
- Version conflicts between pinned and unpinned packages (e.g., `bcrypt==3.2.2` vs `passlib[bcrypt]`)
- Deprecated packages or known-incompatible version combinations
- Missing dependencies that are imported in code but not listed
- Presence of both `langchain-nvidia-ai-endpoints` and `langchain-google-genai` alongside `openai` and `google-genai` — flag redundancy or conflict

### R3. Configuration and Schema Validation

Review `backend/app/config.py` (Pydantic BaseSettings), all files in `backend/app/schemas/`, and all files in `backend/app/models/` for:
- Pydantic v2 compliance (no v1 patterns like `class Config:`, old `validator` decorator, `schema_extra`)
- SQLAlchemy 2.0 model correctness (proper `Mapped[]` annotations, relationship configurations)
- Correct use of `model_config = ConfigDict(...)` pattern

### R4. Structured Bug Report

Produce a single, structured markdown report as an artifact with:
- **Summary** section with total bug count by severity (Critical / High / Medium / Low)
- **Per-file findings** grouped by module (privacy, llm, retrieval, analytics, guardrails, api, middleware, schemas, models, config)
- Each finding must include: file path, line number(s), severity, category (from R1 categories), description of the bug, and the correct API/pattern from current docs
- A **dependency issues** section covering R2 findings

### R5. Do Not Run Tests or Modify Code

This is a read-only audit. Do NOT run pytest, install packages, or modify any source files. The report is the sole deliverable. If you cannot verify something without running code, note it as "needs runtime verification" in the report.

## 2026-08-28T13:49:03Z

# Teamwork Project Prompt — Draft

> Status: Ready for launch — awaiting user approval
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: various agents (full team)

Debug the ModelAudit AI backend codebase by addressing all 120 issues (Critical, High, Medium, and Low) identified in the `backend_code_audit_report.md`.

Working directory: C:\Users\Shakti\Documents\CreditAudit- AI
Integrity mode: development

## Requirements

### R1. Comprehensive Bug Resolution
Implement code fixes for all 120 issues detailed in the `backend_code_audit_report.md` across all affected modules (Privacy, Document Extraction, LLM Routing, NeMo Guardrails, Retrieval, Analytics, and API Endpoints).

### R2. Strict Adherence to Project Rules
Ensure all fixes comply with the project's strict technical stack (Python 3.12, FastAPI, SQLAlchemy 2.0 async, Pydantic v2) and architectural rules (multi-tenancy `tenant_id` filtering, strict privacy masking with bracket notation, and async-first implementation).

## Acceptance Criteria

### Issue Resolution Verification (Agent-as-Judge)
- [ ] An independent agent judge confirms that every Critical and High severity issue from the audit report has a distinct, logically sound code fix applied.
- [ ] An independent agent judge confirms that the Privacy Pipeline (`MaskingPipeline`, `EgressValidator`, `BankNameMatcher`) correctly anchors replacements and prevents all entity leaks as per PRV-01 to PRV-03.
- [ ] An independent agent judge verifies that multi-tenancy isolation (`tenant_id`) is properly enforced in all retrieval and API queries, addressing RET-06 and API-02.
- [ ] An independent agent judge reviews the code to ensure no legacy Pydantic v1 or blocking synchronous I/O patterns remain in async pathways.

## 2026-08-29T18:00:19Z

# Teamwork Project Prompt — Draft

> Status: Step 9 — Assemble and Validate
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: Use a very large team of agents.

Review the Python FastAPI backend codebase for bugs, edge cases, and compatibility issues (Python 3.12, strict tech stack adherence, external APIs like Docling/LLMs, and privacy/multi-tenancy rules), and implement fixes for any identified issues. Use a very large team of agents.

Working directory: c:\Users\Shakti\Documents\CreditAudit- AI
Integrity mode: demo

## Requirements

### R1. Codebase Review
Conduct a comprehensive review of the FastAPI backend (focusing on `backend/app/`) for bugs, edge cases, and compatibility issues. Focus on the required tech stack (Python 3.12, async SQLAlchemy, Pydantic v2) and external API integrations (Docling, NIM/Gemini LLMs).

### R2. Privacy and Multi-tenancy Compliance
Verify that all code adheres strictly to the ModelAudit AI privacy rules (e.g., egress validator runs before LLM calls, proper token masking) and multi-tenancy rules (all DB and Pinecone operations must filter by `tenant_id`).

### R3. Apply Fixes
Implement robust fixes for any identified issues directly in the codebase. You may add new open-source dependencies if they solve a bug elegantly, but avoid significant architectural rewrites.

## Acceptance Criteria

### Code Correctness
- [ ] Every modified file successfully parses in Python 3.12 without syntax errors (verified programmatically via `python -m py_compile`).
- [ ] Pydantic v2 schemas and async function signatures remain intact and correct.

### Rule Adherence
- [ ] An independent agent judge confirms that no fixes violate the privacy or multi-tenancy constraints defined in `AGENTS.md`.
- [ ] Every fix applied includes a brief inline comment explaining the issue it resolves.

## 2026-08-31T17:28:09Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: Full team (multiple agents analyze frontend, backend, and infrastructure separately)

Analyze the extensively changed codebase and generate a comprehensive, step-by-step deployment guide. Do not make any modifications to the existing code. Use a full team of agents to thoroughly analyze all backend, frontend, and infrastructure changes.

Working directory: c:\Users\Shakti\Documents\CreditAudit- AI
Integrity mode: development

## Requirements

### R1. State Analysis
Analyze the current state of the monorepo (backend and frontend) to identify all new environment variables, dependencies, and necessary infrastructure changes (e.g. database migrations, vector DB updates).

### R2. Deployment Guide Generation
Generate a comprehensive, step-by-step deployment guide for deploying the backend to AWS ECS Fargate and the frontend to Vercel. Write the output to a new artifact `deployment_steps.md`. 

### R3. Validation and Safety
The guide must include pre-deployment and post-deployment validation checks for each stage. The team must NOT execute any commands that modify the application source code.

## Acceptance Criteria

### Completeness and Accuracy
- [ ] An independent reviewer agent verifies that all environment variables listed in the backend's config/env files and the frontend's env files are accounted for in the deployment steps.
- [ ] An independent reviewer agent verifies that the guide includes explicitly defined pre-deployment and post-deployment validation steps.

### Safety
- [ ] An independent reviewer agent confirms that the generated guide does not include instructions to modify existing source code, and that the agent team has not modified any source code during this task.
