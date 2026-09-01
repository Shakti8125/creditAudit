## 2026-08-28T17:12:25Z

You are a specialist Worker for ModelAudit AI Milestone 5: NeMo Guardrails Integration & Colang Flows (Generation 2 Replacement).

# Instructions & Context
- You MUST read ORIGINAL_REQUEST.md: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md`
- You MUST read the Master Bug Report: `c:\Users\Shakti\Documents\CreditAudit- AI\backend_code_audit_report.md`
- Project Identity & Rules: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md`
- Domain Skills to load if needed: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\skills\p7-nemo-guardrails\SKILL.md`
- Your working directory for agent metadata is: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m5_gen2`

# Exclusive File Ownership
You exclusively own and may edit:
- `backend/app/services/guardrails/guardrails_service.py`
- `backend/app/services/guardrails/rails.co`
- `backend/app/services/guardrails/config.yml`
- `backend/app/services/guardrails/actions.py`
- `backend/app/services/guardrails/__init__.py`

DO NOT edit files outside this list.

# Assigned Issues to Resolve
1. GRD-01 (Critical): In `guardrails_service.py`, handle dictionary response from `LLMRails.generate_async()` (e.g. `{"role": "assistant", "content": "..."}`) properly extracting string content instead of directly comparing dict with string or assigning dict to string field.
2. GRD-02 (Critical): In `guardrails_service.py`, pass `context={"context": context, "retrieved_contexts": retrieved_contexts}` into `generate_async()` so hallucination checks receive the retrieval context.
3. GRD-03 (Critical): In `rails.co`, define the missing bot utterance `define bot refuse to respond: "I'm sorry, but I cannot verify this answer against the provided credit documentation."` or equivalent referenced in Colang flows.
4. GRD-04 (High): In `config.yml`, set `colang_version: "2.x"` and resolve conflicting `type: main` models.
5. GRD-05 (Medium): In `actions.py`, implement placeholder integrity validation in `check_placeholder_integrity_action` against allowed entity token formats (`[BANK_1]`, `[ORG_1]`, etc.).
6. GRD-06 (Medium): In `actions.py`, preserve comma-formatted numbers in `check_hallucination_action` regex (e.g. `1,250,000`) and filter out English stop words from token overlap calculation.
7. Re-export public guardrails classes in `services/guardrails/__init__.py`.
