from __future__ import annotations

import pytest

from app.services.analytics.model_metrics_extractor import (
    ModelMetricsExtractor,
    parse_population_deciles,
)
from app.services.analytics.policy_checker import PolicyChecker, compute_model_status
from app.services.document_extractor import DocumentExtractor
from app.services.privacy.masking_pipeline import MaskingPipeline
from scripts.demo.fixtures import REPORTS, build_report, decile_table, write_fixtures


@pytest.fixture(scope="module")
def extractor() -> DocumentExtractor:
    return DocumentExtractor()


@pytest.mark.parametrize("target", [0.06, 0.31])
def test_decile_table_sums_to_100_and_matches_the_target_psi(target):
    actual, psi = decile_table(target)
    assert len(actual) == 10
    assert round(sum(actual), 1) == 100.0
    assert abs(psi - target) <= 0.005


@pytest.mark.parametrize("spec", REPORTS, ids=lambda s: s.key)
async def test_the_report_extracts_to_the_metrics_it_states(spec, extractor):
    markdown = await extractor.extract_to_markdown(build_report(spec), spec.filename)
    profile = ModelMetricsExtractor().extract(markdown)

    assert profile.gini.value == spec.gini
    assert profile.auc.value == spec.auc
    assert profile.ks.value == spec.ks
    assert profile.psi.value == pytest.approx(spec.psi, abs=0.005)
    assert profile.hosmer_lemeshow_p_value.value == spec.hosmer_lemeshow_p
    assert profile.brier_score.value == spec.brier


@pytest.mark.parametrize("spec", REPORTS, ids=lambda s: s.key)
async def test_the_report_scores_as_the_demo_expects(spec, extractor):
    markdown = await extractor.extract_to_markdown(build_report(spec), spec.filename)
    report = PolicyChecker().check(ModelMetricsExtractor().extract(markdown))

    assert compute_model_status(report).value == spec.expected_status
    # Every metric agrees, so the demo shows a clean PASS or a clean BREACH, not a mixture.
    assert {result.status for result in report.results} == {spec.expected_status}
    assert len(report.results) == 6


async def test_the_decile_table_feeds_the_population_chart(extractor):
    spec = REPORTS[0]
    markdown = await extractor.extract_to_markdown(build_report(spec), spec.filename)
    deciles = parse_population_deciles(markdown)

    assert len(deciles) == 10
    assert round(sum(d["actual"] for d in deciles), 1) == 100.0
    assert all(d["expected"] == 10.0 for d in deciles)


async def test_the_sign_off_block_gives_the_privacy_inspector_something_to_mask(extractor):
    spec = REPORTS[0]
    markdown = await extractor.extract_to_markdown(build_report(spec), spec.filename)
    masked, registry = MaskingPipeline().mask_document(markdown)

    assert "model.validation@example.com" not in masked
    assert "Amara Okafor" not in masked
    assert "Daniel Whitfield" not in masked
    assert len(registry.get_mapping()) >= 3


def test_write_fixtures_writes_both_files(tmp_path):
    paths = write_fixtures(tmp_path / "demo-data")
    assert [p.name for p in paths] == [s.filename for s in REPORTS]
    assert all(p.stat().st_size > 1000 for p in paths)
