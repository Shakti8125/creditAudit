"""Answer-quality judge: LLM judge with a deterministic token-overlap fallback."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from app.services.evaluation.metrics import groundedness, question_coverage, token_f1
from app.services.evaluation.prompts import JUDGE_SYSTEM_PROMPT, build_judge_prompt, judge_json_schema
from app.services.privacy.egress_validator import EgressValidator
from app.services.privacy.entity_registry import EntityRegistry

logger = logging.getLogger(__name__)

JUDGE_MAX_TOKENS = 400
RATIONALE_CHARS = 300
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True)
class JudgeOutcome:
    """Scores for one generated answer."""

    method: Literal["llm", "deterministic", "none"]
    faithfulness: float | None
    answer_relevance: float | None
    answer_correctness: float | None
    rationale: str | None
    latency_ms: float


class JudgeVerdict(BaseModel):
    """Structured LLM-judge output."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    faithfulness: float
    answer_relevance: float
    correctness: float | None = None
    rationale: str = ""


def _coerce_unit(value: float | None) -> float | None:
    """Coerce a judge score to [0, 1] (a 0-10 scale is rescaled first)."""
    if value is None:
        return None
    v = float(value)
    if 1.0 < v <= 10.0:
        v /= 10.0
    return min(1.0, max(0.0, v))


def deterministic_judge(
    question: str,
    answer: str,
    contexts: Sequence[str],
    reference: str | None,
    latency_ms: float = 0.0,
) -> JudgeOutcome:
    """Token-overlap proxies for faithfulness, relevance and correctness.

    Args:
        question: Masked question.
        answer: Generated answer.
        contexts: Retrieved context strings.
        reference: Masked reference answer, if any.
        latency_ms: Time already spent (e.g. on a failed LLM judge call).

    Returns:
        JudgeOutcome with method ``deterministic``.
    """
    t0 = time.perf_counter()
    faithfulness = groundedness(answer, contexts)
    relevance = question_coverage(question, answer)
    correctness = token_f1(answer, reference) if reference else None
    return JudgeOutcome(
        method="deterministic",
        faithfulness=faithfulness,
        answer_relevance=relevance,
        answer_correctness=correctness,
        rationale="Deterministic token-overlap proxy.",
        latency_ms=latency_ms + (time.perf_counter() - t0) * 1000.0,
    )


def _parse_verdict(raw: str) -> JudgeVerdict:
    """Parse the judge's JSON reply, tolerating markdown fences."""
    text = _FENCE_RE.sub("", (raw or "").strip())
    data: Any = json.loads(text)
    return JudgeVerdict.model_validate(data)


async def judge_answer(
    *,
    llm_router: Any,
    mode: str,
    question_masked: str,
    context: str,
    answer: str,
    reference_masked: str | None,
    registry: EntityRegistry,
    egress: EgressValidator,
) -> JudgeOutcome:
    """Score an answer with the LLM judge, falling back to deterministic proxies.

    Args:
        llm_router: LLMRouter used for the judge call.
        mode: ``auto`` (LLM with fallback) or ``deterministic``.
        question_masked: Masked question.
        context: Retrieved context block.
        answer: Generated answer.
        reference_masked: Masked reference answer, if any.
        registry: Entity registry of the case (for egress validation).
        egress: Egress validator (run before the prompt leaves the system).

    Returns:
        JudgeOutcome.
    """
    if mode == "deterministic":
        return deterministic_judge(question_masked, answer, [context], reference_masked)

    t0 = time.perf_counter()
    try:
        prompt = build_judge_prompt(question_masked, context, answer, reference_masked)
        await run_in_threadpool(egress.validate, prompt, registry)
        raw = await llm_router.generate(
            prompt,
            system_prompt=JUDGE_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=JUDGE_MAX_TOKENS,
            json_schema=judge_json_schema(bool(reference_masked)),
        )
        verdict = _parse_verdict(raw)
        return JudgeOutcome(
            method="llm",
            faithfulness=_coerce_unit(verdict.faithfulness),
            answer_relevance=_coerce_unit(verdict.answer_relevance),
            answer_correctness=_coerce_unit(verdict.correctness) if reference_masked else None,
            rationale=(verdict.rationale or "")[:RATIONALE_CHARS] or None,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
    except Exception as exc:  # noqa: BLE001 - provider SDK/parse errors are heterogeneous
        logger.info("LLM judge unavailable (%s); using deterministic proxy", type(exc).__name__)
        fallback = deterministic_judge(
            question_masked,
            answer,
            [context],
            reference_masked,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
        return JudgeOutcome(
            method="deterministic",
            faithfulness=fallback.faithfulness,
            answer_relevance=fallback.answer_relevance,
            answer_correctness=fallback.answer_correctness,
            rationale=f"LLM judge unavailable ({type(exc).__name__}); deterministic proxy used.",
            latency_ms=fallback.latency_ms,
        )
