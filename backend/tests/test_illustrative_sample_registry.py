"""NEW-02 interim: keep the frontend's "illustrative sample" registry in step with the backend.

The UI labels every built-in sample citation, sample standard and sample rule basis
"illustrative sample, not official text" (``frontend/src/lib/illustrativeSample.ts``). It
decides from the identifiers listed in ``frontend/src/lib/illustrativeSample.json``. These
tests fail if the backend sample data and that list drift apart: a new section source in the
hardcoded corpus, a new seed row, or a new CBUAE-attributed rule basis that nobody labelled,
and also a stale entry that no longer exists in the backend.

When the real regulatory corpus replaces the sample (corpus plan C4/C7) the identifiers
disappear from the backend: empty the registry, delete the frontend label code, and delete
this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.metrics import MetricValue, ModelValidationProfile
from app.services.analytics.policy_checker import PolicyChecker
from app.services.retrieval.hybrid_retriever import CBUAE_REGULATORY_CORPUS
from scripts.seed_regulatory_standards import REGULATORY_STANDARDS

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
REGISTRY_PATH = FRONTEND_DIR / "src" / "lib" / "illustrativeSample.json"

pytestmark = pytest.mark.skipif(
    not FRONTEND_DIR.is_dir(), reason="frontend/ is not part of this checkout"
)

EXPECTED_LABEL = "illustrative sample, not official text"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _norm(values: list[str] | set[str]) -> set[str]:
    return {v.strip().lower() for v in values}


def _full_profile() -> ModelValidationProfile:
    """A profile reporting every metric, so the checker emits every rule it has."""
    metric = MetricValue(value=0.5, unit="absolute", raw_text="0.5", context="")
    return ModelValidationProfile(
        gini=metric,
        auc=metric,
        ks=metric,
        psi=metric,
        hosmer_lemeshow_p_value=metric,
        brier_score=metric,
        pd_accuracy_ratio=metric,
        observed_vs_predicted_default_rate=metric,
        ifrs9_ecl_provision_coverage=metric,
        capital_adequacy_ratio=metric,
        tier_1_ratio=metric,
        npa_ratio=metric,
    )


def test_registry_file_exists_and_has_the_agreed_label() -> None:
    assert REGISTRY_PATH.is_file(), "frontend/src/lib/illustrativeSample.json is missing"
    assert _registry()["label"] == EXPECTED_LABEL


def test_every_hardcoded_corpus_source_is_registered_and_nothing_stale() -> None:
    corpus_sources = {item["source"] for item in CBUAE_REGULATORY_CORPUS}
    assert corpus_sources, "the hardcoded corpus is gone: remove the registry (see module docstring)"
    assert _norm(_registry()["citationSources"]) == _norm(corpus_sources)


def test_every_seed_standard_code_is_registered_and_nothing_stale() -> None:
    seed_codes = {std["code"] for std in REGULATORY_STANDARDS}
    assert _norm(_registry()["standardCodes"]) == _norm(seed_codes)


def test_every_cbuae_rule_basis_the_checker_emits_is_registered_and_nothing_stale() -> None:
    report = PolicyChecker().check(_full_profile())
    assert report.results, "the checker produced no results"
    cbuae_bases = {r.rule_basis for r in report.results if "cbuae" in r.rule_basis.lower()}
    assert cbuae_bases, "no CBUAE-attributed rule basis left: remove the registry"
    assert _norm(_registry()["ruleBases"]) == _norm(cbuae_bases)


def test_registry_lists_are_plain_nonblank_strings() -> None:
    registry = _registry()
    for key in ("citationSources", "standardCodes", "ruleBases"):
        values = registry[key]
        assert isinstance(values, list)
        assert all(isinstance(v, str) and v.strip() for v in values), key
        assert len(_norm(values)) == len(values), f"{key} has duplicates"
