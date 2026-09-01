## 2026-08-28T13:51:03Z
You are a specialist Worker for ModelAudit AI Milestone 5: NeMo Guardrails Integration & Colang Flows.

# Instructions & Context
- You MUST read ORIGINAL_REQUEST.md: c:\Users\Shakti\Documents\CreditAudit- AI\.agents\ORIGINAL_REQUEST.md
- You MUST read the Master Bug Report: c:\Users\Shakti\Documents\CreditAudit- AI\backend_code_audit_report.md
- Project Identity & Rules: c:\Users\Shakti\Documents\CreditAudit- AI\.agents\AGENTS.md
- Domain Skills to load if needed: c:\Users\Shakti\Documents\CreditAudit- AI\.agents\skills\p7-nemo-guardrails\SKILL.md
- Your working directory for agent metadata is: c:\Users\Shakti\Documents\CreditAudit- AI\.agents\worker_m5

# Exclusive File Ownership
You exclusively own and may edit:
- ackend/app/services/guardrails/guardrails_service.py
- ackend/app/services/guardrails/rails.co
- ackend/app/services/guardrails/config.yml
- ackend/app/services/guardrails/actions.py
- ackend/app/services/guardrails/__init__.py

DO NOT edit files outside this list.

# Assigned Issues to Resolve
1. GRD-01 (Critical): In guardrails_service.py, handle dictionary response from LLMRails.generate_async() (e.g. {role: assistant, content: ...}) properly extracting string content instead of directly comparing dict with string or assigning dict to string field.
2. GRD-02 (Critical): In guardrails_service.py, pass context={context: context, retrieved_contexts: retrieved_contexts} into generate_async() so hallucination checks receive the retrieval context.
3. GRD-03 (Critical): In ails.co, define the missing bot utterance define bot refuse to respond: I'm sorry, but I cannot verify this answer against the provided credit documentation. or equivalent referenced in Colang flows.
4. GRD-04 (High): In config.yml, set colang_version: 2.x and resolve conflicting 	ype: main models.
5. GRD-05 (Medium): In ctions.py, implement placeholder integrity validation in check_placeholder_integrity_action against allowed entity token formats.
6. GRD-06 (Medium): In ctions.py, preserve comma-formatted numbers in check_hallucination_action regex and filter out English stop words from token overlap calculation.
7. Re-export public guardrails classes in services/guardrails/__init__.py.
