"""The 22 default golden cases derived from ``CBUAE_REGULATORY_CORPUS``.

Every keyword set was chosen so that it reaches the default keyword threshold
(ceil(60%)) on its own section's text and on no other section; the two
multi-target cases make Recall@k differ from Hit@k.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rag_eval import EvalCaseOrigin, RagEvalCase
from app.models.user import _utc_now
from app.services.retrieval.hybrid_retriever import CBUAE_REGULATORY_CORPUS


@dataclass(frozen=True)
class DefaultTargetSpec:
    """A relevance target pointing at one corpus section (0-based index)."""

    section_index: int
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class DefaultCaseSpec:
    """A default golden case."""

    key: str
    question: str
    reference_answer: str
    targets: tuple[DefaultTargetSpec, ...]


def _t(section_index: int, *keywords: str) -> DefaultTargetSpec:
    """Shorthand for a DefaultTargetSpec."""
    return DefaultTargetSpec(section_index=section_index, keywords=tuple(keywords))


DEFAULT_CASE_SPECS: tuple[DefaultCaseSpec, ...] = (
    DefaultCaseSpec(
        "cbuae-s01-q1",
        "Who must approve the model risk management framework?",
        "The Model Risk Management framework must be approved by the Board of Directors and define model risk appetite.",
        (_t(0, "Board of Directors", "risk appetite"),),
    ),
    DefaultCaseSpec(
        "cbuae-s01-q2",
        "What must the model risk management framework define regarding lines of defense and responsibilities?",
        "The MRM framework must define model risk appetite, the three lines of defense, and the roles and "
        "responsibilities of model owners, developers and independent model validation units.",
        (_t(0, "three lines of defense", "model owners"),),
    ),
    DefaultCaseSpec(
        "cbuae-s02-q1",
        "How must models be classified into tiers under the model inventory requirements?",
        "Models are tiered into Tier 1 (high), Tier 2 (medium) and Tier 3 (low materiality) based on financial "
        "exposure, regulatory capital impact, algorithmic complexity and decision autonomy, and recorded in a "
        "centralized model inventory.",
        (_t(1, "Tier 1", "Tier 2", "Tier 3", "Materiality"),),
    ),
    DefaultCaseSpec(
        "cbuae-s02-q2",
        "How frequently must Tier 1 models be validated?",
        "Tier 1 (high materiality) models require annual validation.",
        (_t(1, "Tier 1", "annual validation"),),
    ),
    DefaultCaseSpec(
        "cbuae-s03-q1",
        "How much historical data is required when developing a credit risk model?",
        "Development data must be representative and cover at least one full economic cycle, a minimum of 5-7 years.",
        (_t(2, "economic cycle", "5-7 years"),),
    ),
    DefaultCaseSpec(
        "cbuae-s03-q2",
        "Which data quality treatments must be documented in the Model Development Document?",
        "Completeness checks, outlier treatment, missing value imputation and sample selection rationale must be "
        "documented in the Model Development Document (MDD).",
        (_t(2, "outlier treatment", "missing value imputation", "Model Development Document"),),
    ),
    DefaultCaseSpec(
        "cbuae-s04-q1",
        "What is the minimum Gini coefficient required for credit scoring models?",
        "Credit scoring and rating models must achieve a Gini coefficient of at least 0.40 (40%).",
        (_t(3, "Gini", "0.40"),),
    ),
    DefaultCaseSpec(
        "cbuae-s04-q2",
        "What AUC and KS thresholds must rating models meet?",
        "The minimum benchmarks are AUC-ROC of at least 0.70 and a Kolmogorov-Smirnov (KS) statistic of at least 30 (30%).",
        (_t(3, "AUC", "0.70", "Kolmogorov-Smirnov"),),
    ),
    DefaultCaseSpec(
        "cbuae-s05-q1",
        "Which statistical tests are required for PD calibration?",
        "PD calibration requires binomial tests, traffic light tests, Hosmer-Lemeshow goodness-of-fit tests and "
        "Brier score evaluation.",
        (_t(4, "binomial", "traffic light", "Hosmer-Lemeshow"),),
    ),
    DefaultCaseSpec(
        "cbuae-s05-q2",
        "What Brier score target applies to PD model calibration?",
        "The Brier score target is 0.15 or lower.",
        (_t(4, "Brier", "0.15"),),
    ),
    DefaultCaseSpec(
        "cbuae-s06-q1",
        "At what PSI level is recalibration or rebuild mandatory?",
        "A PSI of 0.25 or higher indicates a significant shift that triggers mandatory recalibration or rebuild.",
        (_t(5, "PSI", "0.25", "recalibration"),),
    ),
    DefaultCaseSpec(
        "cbuae-s06-q2",
        "Which indices are used to monitor population and characteristic drift?",
        "Drift is monitored with the Population Stability Index (PSI) and the Characteristic Stability Index (CSI).",
        (_t(5, "Population Stability Index", "Characteristic Stability Index"),),
    ),
    DefaultCaseSpec(
        "cbuae-s07-q1",
        "What days-past-due backstop applies to SICR assessment under IFRS 9?",
        "SICR criteria must include the mandatory 30 days past due (DPD) backstop alongside quantitative lifetime "
        "PD changes and qualitative watchlist flags.",
        (_t(6, "30 days past due", "SICR"),),
    ),
    DefaultCaseSpec(
        "cbuae-s07-q2",
        "Which macroeconomic scenarios must IFRS 9 ECL models incorporate?",
        "ECL models must incorporate probability-weighted forward-looking baseline, upside and downside "
        "macroeconomic scenarios.",
        (_t(6, "baseline", "upside", "downside"),),
    ),
    DefaultCaseSpec(
        "cbuae-s08-q1",
        "Which macroeconomic shocks should credit risk stress tests cover?",
        "Stress tests should cover severe but plausible shocks including real estate shocks, oil price volatility "
        "and interest rate fluctuations.",
        (_t(7, "real estate", "oil price", "interest rate"),),
    ),
    DefaultCaseSpec(
        "cbuae-s08-q2",
        "Which capital and provisioning metrics must stress testing evaluate?",
        "Stress testing must evaluate the impact on risk-weighted assets (RWA), impairment provisions and capital "
        "adequacy ratios.",
        (_t(7, "risk-weighted assets", "impairment provisions", "capital adequacy"),),
    ),
    DefaultCaseSpec(
        "cbuae-s09-q1",
        "What independence requirements apply to the model validation unit?",
        "Independent Model Validation units must maintain strict organizational and reporting independence from "
        "model development.",
        (_t(8, "Independent Model Validation", "independence"),),
    ),
    DefaultCaseSpec(
        "cbuae-s09-q2",
        "What activities does independent model validation encompass?",
        "Validation covers conceptual soundness review, developmental evidence verification, replication, outcome "
        "analysis, benchmarking and implementation verification.",
        (_t(8, "conceptual soundness", "replication", "benchmarking"),),
    ),
    DefaultCaseSpec(
        "cbuae-s10-q1",
        "How often must ongoing monitoring reports be escalated to the Board Risk Committee?",
        "Ongoing monitoring reports, override tracking, policy exception rates and validation findings must be "
        "reported quarterly to the Board Risk Committee.",
        (_t(9, "quarterly", "Board Risk Committee"),),
    ),
    DefaultCaseSpec(
        "cbuae-s10-q2",
        "What is the purpose of an Early Warning System for credit portfolios?",
        "Early Warning Systems detect deteriorating borrower creditworthiness and emerging portfolio stress.",
        (_t(9, "Early Warning Systems", "creditworthiness"),),
    ),
    DefaultCaseSpec(
        "cbuae-multi-01",
        "For a Tier 1 credit scoring model, how often is validation required and what minimum Gini applies?",
        "Tier 1 models require annual validation and credit scoring models must reach a Gini coefficient of at "
        "least 0.40.",
        (_t(1, "Tier 1", "annual validation"), _t(3, "Gini", "0.40")),
    ),
    DefaultCaseSpec(
        "cbuae-multi-02",
        "Which calibration tests and stability indices should ongoing monitoring of a PD model include?",
        "Ongoing monitoring should include calibration tests such as binomial and Hosmer-Lemeshow tests plus "
        "stability tracking with the Population Stability Index (PSI).",
        (_t(4, "binomial", "Hosmer-Lemeshow"), _t(5, "Population Stability Index", "PSI")),
    ),
)


def build_expected_refs(spec: DefaultCaseSpec) -> list[dict[str, Any]]:
    """Expected refs (ExpectedRef dicts) for a default case.

    Args:
        spec: Default case spec.

    Returns:
        One ref per target with the corpus source/section plus keywords.
    """
    refs: list[dict[str, Any]] = []
    for target in spec.targets:
        item = CBUAE_REGULATORY_CORPUS[target.section_index]
        refs.append(
            {
                "source": item["source"],
                "section": item["section"],
                "keywords": list(target.keywords),
                "min_keyword_hits": None,
                "chunk_index": None,
            }
        )
    return refs


def _new_case(spec: DefaultCaseSpec, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> RagEvalCase:
    """ORM row for a default case."""
    now = _utc_now()
    return RagEvalCase(
        tenant_id=tenant_id,
        created_by=user_id,
        question=spec.question,
        reference_answer=spec.reference_answer,
        expected_refs_json=build_expected_refs(spec),
        document_id=None,
        origin=EvalCaseOrigin.DEFAULT.value,
        default_key=spec.key,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


async def ensure_default_cases(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> int:
    """Seed every default case when the tenant has no cases at all (any origin or state).

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        user_id: User credited as creator.

    Returns:
        Number of cases inserted (0 or 22).
    """
    existing = (
        await db.execute(select(func.count()).select_from(RagEvalCase).where(RagEvalCase.tenant_id == tenant_id))
    ).scalar_one()
    if existing:
        return 0
    db.add_all([_new_case(spec, tenant_id, user_id) for spec in DEFAULT_CASE_SPECS])
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request (e.g. two first-time GET /rag/eval/cases) seeded the
        # defaults first; the (tenant_id, default_key) unique constraint rejected ours.
        await db.rollback()
        return 0
    return len(DEFAULT_CASE_SPECS)


async def restore_default_cases(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> int:
    """Insert the default cases whose key is missing for the tenant.

    Args:
        db: Async session.
        tenant_id: Tenant from the JWT.
        user_id: User credited as creator.

    Returns:
        Number of cases inserted.
    """
    present = set(
        (
            await db.execute(
                select(RagEvalCase.default_key).where(
                    RagEvalCase.tenant_id == tenant_id, RagEvalCase.default_key.is_not(None)
                )
            )
        ).scalars().all()
    )
    missing = [spec for spec in DEFAULT_CASE_SPECS if spec.key not in present]
    if missing:
        db.add_all([_new_case(spec, tenant_id, user_id) for spec in missing])
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent seed/restore inserted the same default keys first.
            await db.rollback()
            return 0
    return len(missing)
