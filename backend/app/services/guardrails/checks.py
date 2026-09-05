from __future__ import annotations

import logging
from dataclasses import dataclass

from app.services.guardrails.actions import (
    check_hallucination_action,
    check_jailbreak_action,
    check_off_topic_action,
    check_placeholder_integrity_action,
    check_prompt_injection_action,
    verify_financial_arithmetic_action,
)

logger = logging.getLogger(__name__)

# Heuristic token-overlap score from check_hallucination_action: 0.0 means the
# answer is fully grounded in the retrieved context, 1.0 means no overlap at all.
HALLUCINATION_THRESHOLD = 0.6


@dataclass
class GuardrailViolation:
    """A single failed guardrail check.

    ``reason`` is a stable machine-readable slug; ``detail`` is safe to surface
    to the caller (it never echoes the offending content back).
    """

    reason: str
    detail: str


async def run_input_guardrails(
    user_message: str,
    *,
    check_off_topic: bool = True,
) -> GuardrailViolation | None:
    """Run the input-side rails over untrusted text heading into an LLM prompt.

    Calls the ``@action``-decorated functions in ``actions.py`` directly rather
    than going through ``GuardrailsService``/Colang — none of them invoke an LLM,
    so this keeps the multi-provider failover and streaming paths untouched.

    Note the inverted conventions between the underlying actions: the jailbreak
    and prompt-injection checks return ``True`` when the message is *safe*, while
    the off-topic check returns ``True`` when the message *is* off-topic.

    ``check_off_topic`` is opt-out for surfaces where the "user message" is
    actually document content (gap analysis), which legitimately contains prose
    that the off-topic keyword list would misfire on.

    Returns ``None`` when the message passes every check.
    """
    if not user_message or not user_message.strip():
        return None

    if not await check_jailbreak_action(context={"last_user_message": user_message}):
        return GuardrailViolation(
            reason="jailbreak",
            detail="Request blocked: the input contains a jailbreak pattern.",
        )

    if not await check_prompt_injection_action(context={"last_user_message": user_message}):
        return GuardrailViolation(
            reason="prompt_injection",
            detail="Request blocked: the input contains a prompt-injection pattern.",
        )

    if check_off_topic and await check_off_topic_action(
        context={"last_user_message": user_message}
    ):
        return GuardrailViolation(
            reason="off_topic",
            detail=(
                "Request blocked: this assistant only answers questions about credit "
                "risk model validation and CBUAE Model Management Guidelines."
            ),
        )

    return None


async def run_output_guardrails(
    bot_message: str,
    context: str = "",
    retrieved_contexts: list[str] | None = None,
) -> GuardrailViolation | None:
    """Run the output-side rails over a generated answer.

    The hallucination check is grounding-based and is skipped entirely when no
    grounding material is supplied (``check_hallucination_action`` already
    returns ``0.0`` in that case), so non-retrieval callers can omit it.

    Returns ``None`` when the message passes every check.
    """
    if not bot_message or not bot_message.strip():
        return None

    if not await check_placeholder_integrity_action(context={"last_bot_message": bot_message}):
        return GuardrailViolation(
            reason="broken_placeholder",
            detail="Generated response contains a malformed privacy placeholder.",
        )

    if not await verify_financial_arithmetic_action(context={"last_bot_message": bot_message}):
        return GuardrailViolation(
            reason="arithmetic_inconsistency",
            detail="Generated response contains inconsistent or out-of-range model metrics.",
        )

    score = await check_hallucination_action(
        context={
            "last_bot_message": bot_message,
            "context": context,
            "retrieved_contexts": retrieved_contexts or [],
        }
    )
    if score > HALLUCINATION_THRESHOLD:
        return GuardrailViolation(
            reason="hallucination",
            detail=(
                f"Generated response is poorly grounded in the retrieved context "
                f"(score {score:.2f} > {HALLUCINATION_THRESHOLD})."
            ),
        )

    return None
