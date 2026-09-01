# ModelAudit AI — Multi-Agent Orchestration Guide

This guide is for the **Main Agent** (you) to orchestrate the development of ModelAudit AI using a team of specialized subagents.

## The Strategy
Instead of writing all the code yourself, your job is to:
1. Launch specialized subagents concurrently using the `invoke_subagent` tool.
2. Direct each subagent to use its designated Antigravity Skill (`.agents/skills/<skill-name>/SKILL.md`).
3. Wait for the subagents to finish their sub-parts.
4. Review, combine, and verify their work.
5. Move on to the next phase.

## Phase Execution Playbook

### Phase 1: Foundation & Core Backend
Use `invoke_subagent` to launch two parallel agents:

**Subagent 1:**
- `Role`: "Project Scaffolder"
- `Prompt`: "You are responsible for Phase 1 part A. Read the skill at `.agents/skills/p1-project-scaffold/SKILL.md` and execute all steps to scaffold the repository, create the Docker configuration, and set up the dependencies."

**Subagent 2:**
- `Role`: "Database Auth Engineer"
- `Prompt`: "You are responsible for Phase 1 part B. Read the skill at `.agents/skills/p1-database-auth/SKILL.md` and execute all steps to build the PostgreSQL database layer, schemas, and JWT authentication system."

*Wait for both to complete, run the `docker compose config` and `pytest backend/tests/test_auth.py` verification steps, then proceed to Phase 2.*

---

### Phase 2: Document Processing & Privacy Pipeline
Use `invoke_subagent` to launch two parallel agents:

**Subagent 1:**
- `Role`: "Document Extraction Engineer"
- `Prompt`: "Read the skill at `.agents/skills/p2-document-extraction/SKILL.md` and build the IBM Docling PDF/DOCX extraction service, Markdown chunker, and the `/documents` API endpoints."

**Subagent 2:**
- `Role`: "Privacy Pipeline Engineer"
- `Prompt`: "Read the skill at `.agents/skills/p2-privacy-pipeline/SKILL.md` and build the complete zero-trust privacy masking pipeline including the Bank Matcher, NER Masker, Entity Registry, and Egress Validator."

*Wait for both to complete, verify no entities leak in the masking pipeline tests, then proceed to Phase 3 & 4.*

---

### Phases 3 & 4: Analytics & LLM Routing
Use `invoke_subagent` to launch two parallel agents:

**Subagent 1:**
- `Role`: "Analytics Engine Developer"
- `Prompt`: "Read the skill at `.agents/skills/p3-model-validation-analytics/SKILL.md` and implement the ModelMetricsExtractor, PolicyChecker, and EarlyWarningDetector."

**Subagent 2:**
- `Role`: "LLM Routing Engineer"
- `Prompt`: "Read the skill at `.agents/skills/p4-llm-routing/SKILL.md` and implement the multi-provider LLM routing layer for NVIDIA NIM and Gemini, including the circuit breaker."

*Wait for both to complete and run unit tests, then proceed to Phase 5 & 6.*

---

### Phases 5 & 6: Hybrid RAG & API Endpoints
Use `invoke_subagent` to launch two parallel agents:

**Subagent 1:**
- `Role`: "RAG Pipeline Engineer"
- `Prompt`: "Read the skill at `.agents/skills/p5-hybrid-rag/SKILL.md` and build the hybrid retrieval pipeline combining BM25, Pinecone dense retrieval, RRF fusion, and cross-encoder reranking."

**Subagent 2:**
- `Role`: "API Streaming Developer"
- `Prompt`: "Read the skill at `.agents/skills/p6-api-streaming-ratelimit/SKILL.md` and implement the `/query`, `/compare`, and `/gap-analysis` endpoints with SSE streaming, and the Upstash Redis Lua rate limiter."

*Wait for completion, verify SSE and rate limiting, then proceed to final phases.*

---

### Phases 7, 8 & 9: Guardrails, Frontend, and CI/CD
Use `invoke_subagent` to launch three parallel agents:

**Subagent 1:**
- `Role`: "AI Safety Engineer"
- `Prompt`: "Read the skill at `.agents/skills/p7-nemo-guardrails/SKILL.md` and configure NeMo Guardrails 2.0 with Colang flows and custom Python actions."

**Subagent 2:**
- `Role`: "Frontend Developer"
- `Prompt`: "Read the skill at `.agents/skills/p8-react-frontend/SKILL.md` and scaffold the Vite+React+TypeScript frontend with routing and components."

**Subagent 3:**
- `Role`: "DevOps Engineer"
- `Prompt`: "Read the skill at `.agents/skills/p9-cicd-deployment/SKILL.md` and set up the GitHub Actions CI/CD workflows and AWS ECS Fargate deployment configs."

*After this final batch completes, the project is fully scaffolded and implemented.*
