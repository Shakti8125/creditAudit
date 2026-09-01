---
name: p7-nemo-guardrails
description: >-
  Use this skill to integrate NeMo Guardrails 2.0 with Colang 2.0 flows for ModelAudit AI Phase 7.
---
# Phase 7: NeMo Guardrails Integration

This skill instructs you to integrate NeMo Guardrails 2.0 with Colang 2.0 flows.

## Steps

### 1. NeMo Guardrails Config
Create `backend/app/services/guardrails/config.yml`:
- Register NVIDIA NIM via `langchain-nvidia-ai-endpoints` as a LangChain provider.
- Register Google Gemini via `langchain-google-genai` as a LangChain provider.
- Set the main model to use whichever provider the LLMRouter selects.
- Input rails: check jailbreak, check prompt injection, mask pii entities.
- Dialog rails: enforce model validation domain boundary.
- Output rails: check hallucination, verify model metric arithmetic, check placeholder integrity.

### 2. Colang 2.0 Flows
Create `backend/app/services/guardrails/rails.co`:
- `define flow check jailbreak` -> execute check_jailbreak_action
- `define flow enforce credit domain boundary` -> reject off-topic queries
- Off-topic examples for model validation context:
  - "Write me a Python script", "What stocks should I buy?", "Who is the president?"
  - "Can you help me cook dinner?", "Write a poem about banking"
- `define bot refuse off_topic` -> "I am ModelAudit AI, specialized in credit risk model validation and CBUAE MMG regulatory compliance."
- `define flow check hallucination against context` -> threshold 0.3
- `define flow verify financial calculation consistency` -> verify Gini, AUC, KS, PSI values

### 3. Custom Python Actions
Create `backend/app/services/guardrails/actions.py`:
- `@action(name="verify_financial_arithmetic_action")` - Verifies model validation metrics:
  - Checks Gini percentages are between 0-100
  - Checks AUC values are between 0-1
  - Checks KS percentages are between 0-100
  - Checks PSI values are non-negative
  - Cross-validates: if Gini is mentioned, AUC should be approximately (Gini/100 + 1) / 2
- `@action(name="check_hallucination_action")` - Grounding overlap check:
  - Decimal-safe sentence tokenization (don't split on numbers like 1.25 or 33.2)
  - Word overlap threshold: 30% minimum
  - Returns hallucination probability 0.0 to 1.0
- `@action(name="check_placeholder_integrity_action")` - Ensure no unmasked entities in output

### 4. Guardrails Service
Create `backend/app/services/guardrails/guardrails_service.py`:
- Class `GuardrailsService`
- Initializes NeMo Guardrails with config from the guardrails directory.
- Method: `generate_with_guardrails(prompt, context, retrieved_contexts) -> GuardrailsResult`
- `GuardrailsResult` Pydantic schema: `response: str | None, blocked: bool, block_reason: str | None, rail_type: str | None`
- If blocked, returns user-friendly error message.
- Integrates with LLMRouter for the underlying generation.

## Verification
Test jailbreak prompt -> blocked. Test off-topic -> refused. Test hallucinated response -> flagged. Test valid response -> passed.
