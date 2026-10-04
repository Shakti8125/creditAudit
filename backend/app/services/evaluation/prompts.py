"""Prompt constants shared by the RAG endpoints and the offline evaluation runner.

``REGULATORY_SYSTEM_PROMPT`` and ``QUERY_SYSTEM_PROMPT`` are the production system
prompts of ``/regulatory/search`` and ``/query``; the runner reuses them so offline
generation matches what users get.
"""

from __future__ import annotations

from typing import Any, Sequence

from app.schemas.retrieval import Citation
from app.services.privacy.doc_alias import assign_doc_aliases
from app.services.privacy.entity_registry import EntityRegistry

REGULATORY_SYSTEM_PROMPT = (
    "You are ModelAudit AI, a regulatory expert in CBUAE Model Management Guidelines (MMG). "
    "Answer the user's question based strictly on the provided regulatory context. "
    "Cite the source using the format [Source: <source_name>, Section: <section_name>]."
)

QUERY_SYSTEM_PROMPT = (
    "You are ModelAudit AI, a virtual analyst expert in credit risk model validation and CBUAE Model Management Guidelines (MMG). "
    "Answer the user's question based strictly on the provided context and the conversation history. "
    "When referencing information, you MUST cite the source using the format [Source: <source_name>, Section: <section_name>]. "
    "Copy <source_name> exactly as the Source label appears in the context: uploaded documents are labelled DOC-1, DOC-2 and so on, "
    "and you must never invent or guess a file name."
)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of retrieval-augmented answers about CBUAE model risk regulation. "
    "Tokens like [ORG_1] or [BANK_1] are privacy placeholders; treat them as opaque names. "
    "Respond only with JSON."
)

JUDGE_CONTEXT_CHARS = 8000
JUDGE_TEXT_CHARS = 4000


def format_context(
    citations: Sequence[Citation],
    registry: EntityRegistry | None = None,
    primary_document_id: str | None = None,
) -> str:
    """Render retrieved citations exactly as the production endpoints do.

    A tenant document is labelled with its ``DOC-n`` alias, never with its
    filename or internal id (QA-004). Public regulatory text keeps its corpus id.

    Args:
        citations: Retrieved citations in rank order. Citations that already carry
            an ``alias`` keep it; the others are numbered here.
        registry: Optional session registry. When given, registered entities that
            appear raw in the *public* regulatory text are replaced by their tokens
            (defence in depth: it can only remove raw strings, and the egress
            validator still runs on the final prompt). Tenant text is not touched.
        primary_document_id: Document the request is scoped to; it is ``DOC-1``.

    Returns:
        The context block placed in the user prompt.
    """
    aliases = assign_doc_aliases(citations, primary_document_id)
    blocks: list[str] = []
    for c in citations:
        if c.document_id:
            label, section, text = c.alias or aliases[c.document_id], c.section, c.text
        else:
            label, section, text = c.source, c.section, c.text
            if registry is not None:
                label, section, text = (registry.apply_to_text(v) for v in (label, section, text))
        blocks.append(f"Source: {label}\nSection: {section}\nContent: {text}")
    return "\n\n".join(blocks)


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
