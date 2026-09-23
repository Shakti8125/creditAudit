"""Prompt constants shared by the RAG endpoints and the offline evaluation runner.

``REGULATORY_SYSTEM_PROMPT`` and ``QUERY_SYSTEM_PROMPT`` are the production system
prompts of ``/regulatory/search`` and ``/query``; the runner reuses them so offline
generation matches what users get.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.schemas.retrieval import Citation

REGULATORY_SYSTEM_PROMPT = (
    "You are ModelAudit AI, a regulatory expert in CBUAE Model Management Guidelines (MMG). "
    "Answer the user's question based strictly on the provided regulatory context. "
    "Cite the source using the format [Source: <source_name>, Section: <section_name>]."
)

QUERY_SYSTEM_PROMPT = (
    "You are ModelAudit AI, a virtual analyst expert in credit risk model validation and CBUAE Model Management Guidelines (MMG). "
    "Answer the user's question based strictly on the provided context and the conversation history. "
    "When referencing information, you MUST cite the source using the format [Source: <source_name>, Section: <section_name>]."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of retrieval-augmented answers about CBUAE model risk regulation. "
    "Tokens like [ORG_1] or [BANK_1] are privacy placeholders; treat them as opaque names. "
    "Respond only with JSON."
)

JUDGE_CONTEXT_CHARS = 8000
JUDGE_TEXT_CHARS = 4000


def format_context(citations: Sequence[Citation]) -> str:
    """Render retrieved citations exactly as the production endpoints do.

    Args:
        citations: Retrieved citations in rank order.

    Returns:
        The context block placed in the user prompt.
    """
    return "\n\n".join(f"Source: {c.source}\nSection: {c.section}\nContent: {c.text}" for c in citations)


def build_judge_prompt(question: str, context: str, answer: str, reference: str | None) -> str:
    """Build the LLM-judge user prompt (all inputs must already be masked).

    Args:
        question: Masked question.
        context: Retrieved context block.
        answer: Candidate answer.
        reference: Masked reference answer, if any.

    Returns:
        Prompt text.
    """
    parts = [
        f"Question:\n{question}\n\n",
        f"Retrieved context:\n{context[:JUDGE_CONTEXT_CHARS]}\n\n",
        f"Candidate answer:\n{answer[:JUDGE_TEXT_CHARS]}\n\n",
    ]
    if reference:
        parts.append(f"Reference answer:\n{reference[:JUDGE_TEXT_CHARS]}\n\n")
    parts.append(
        "Score each criterion from 0.0 to 1.0:\n"
        "- faithfulness: fraction of the answer's factual claims directly supported by the retrieved context.\n"
        "- answer_relevance: how directly and completely the answer addresses the question (ignore correctness).\n"
    )
    if reference:
        parts.append("- correctness: agreement with the reference answer's key facts.\n")
    parts.append(
        "Return JSON with keys faithfulness, answer_relevance"
        + (", correctness" if reference else "")
        + ", rationale (<= 300 characters)."
    )
    return "".join(parts)


def judge_json_schema(with_reference: bool) -> dict[str, Any]:
    """JSON schema for the judge verdict.

    Plain ``number``/``string`` types only: Gemini's ``response_schema`` rejects
    type arrays, so ``correctness`` is present only when a reference exists.

    Args:
        with_reference: Whether the case has a reference answer.

    Returns:
        JSON schema dict.
    """
    properties: dict[str, Any] = {
        "faithfulness": {"type": "number"},
        "answer_relevance": {"type": "number"},
    }
    required = ["faithfulness", "answer_relevance"]
    if with_reference:
        properties["correctness"] = {"type": "number"}
        required.append("correctness")
    properties["rationale"] = {"type": "string"}
    required.append("rationale")
    return {"type": "object", "properties": properties, "required": required}
