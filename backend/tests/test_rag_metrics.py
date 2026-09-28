from __future__ import annotations

import math

import pytest

from app.services.evaluation.metrics import (
    RelevanceTarget,
    RetrievedItem,
    classify_score_kind,
    content_tokens,
    count_inline_citations,
    dcg_at_k,
    estimate_tokens,
    first_relevant_rank,
    groundedness,
    hit_at_k,
    judge_relevance,
    keyword_hits,
    mean_or_none,
    metric_curves,
    ndcg_at_k,
    normalize_score,
    normalize_text,
    percentile,
    precision_at_k,
    question_coverage,
    recall_at_k,
    reciprocal_rank_at_k,
    required_keyword_hits,
    safe_rate,
    score_case,
    section_matches,
    target_matches,
    text_fingerprint,
    token_f1,
    tokenize,
)

RELEVANCES = [0, 1, 0, 1]
MATCHED = [[], [0], [], [1]]


def test_worked_example_at_k4() -> None:
    assert hit_at_k(RELEVANCES, 4) == 1.0
    assert precision_at_k(RELEVANCES, 4) == 0.5
    assert reciprocal_rank_at_k(RELEVANCES, 4) == 0.5
    assert first_relevant_rank(RELEVANCES, 4) == 2
    assert recall_at_k(MATCHED, 2, 4) == 1.0
    assert recall_at_k(MATCHED, 2, 2) == 0.5
    assert dcg_at_k(RELEVANCES, 4) == pytest.approx(1.0616, abs=1e-4)
    assert ndcg_at_k(MATCHED, 4, 2) == pytest.approx(0.6509, abs=1e-4)


def test_score_case_bundles_metrics() -> None:
    scores = score_case(RELEVANCES, MATCHED, 2, 4)
    assert scores.hit is True
    assert scores.first_relevant_rank == 2
    assert scores.targets_matched == 2
    assert scores.ndcg == pytest.approx(0.6509, abs=1e-4)
    at1 = score_case(RELEVANCES, MATCHED, 2, 1)
    assert at1.hit is False and at1.reciprocal_rank == 0.0 and at1.first_relevant_rank is None


def test_ndcg_never_exceeds_one_when_several_items_match_one_target() -> None:
    assert ndcg_at_k([[0], [0], [0]], 3, 1) == pytest.approx(1.0)


def test_ndcg_does_not_penalise_duplicate_chunks_of_a_covered_target() -> None:
    # Retrieving a second chunk of an already-covered section must not lower nDCG.
    assert ndcg_at_k([[0], [], [], [], []], 5, 1) == pytest.approx(1.0)
    assert ndcg_at_k([[0], [], [0], [], []], 5, 1) == pytest.approx(1.0)
    # A later rank covering a *new* target still earns gain; a duplicate does not.
    with_new = ndcg_at_k([[0], [0], [1]], 3, 2)
    assert with_new == pytest.approx((1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3)))
    assert ndcg_at_k([[0], [0], []], 3, 2) < with_new


def test_ndcg_is_zero_without_targets_or_hits() -> None:
    assert ndcg_at_k([[], []], 2, 0) == 0.0
    assert ndcg_at_k([[], []], 2, 1) == 0.0


def test_precision_denominator_is_k_even_with_fewer_items() -> None:
    assert precision_at_k([1], 5) == pytest.approx(0.2)


@pytest.mark.parametrize("fn", [hit_at_k, precision_at_k, reciprocal_rank_at_k, dcg_at_k])
def test_k_zero_raises(fn) -> None:
    with pytest.raises(ValueError):
        fn([1], 0)


def test_k_zero_raises_for_recall_and_ndcg() -> None:
    with pytest.raises(ValueError):
        recall_at_k([[0]], 1, 0)
    with pytest.raises(ValueError):
        ndcg_at_k([[0]], 0, 1)


def test_section_matching_is_prefix_safe() -> None:
    assert section_matches("Section 1", "Section 10 - Early Warning Systems") is False
    assert section_matches("Section 1", "Section 1 - Governance & Model Risk Management Framework") is True
    assert section_matches("section 4 - quantitative validation", "Section 4 - Quantitative Validation") is True


def test_normalisation_is_case_and_dash_insensitive() -> None:
    assert normalize_text("Hosmer–Lemeshow  TEST") == "hosmer-lemeshow test"
    assert section_matches("Section 5 — Calibration", "Section 5 - Calibration & Goodness-of-Fit Standards")
    assert keyword_hits("Uses the Hosmer-Lemeshow test", ["hosmer–lemeshow"]) == 1


def test_required_keyword_hits() -> None:
    assert required_keyword_hits(["a", "b", "c", "d"], None) == 3
    assert required_keyword_hits(["a"], None) == 1
    assert required_keyword_hits(["a", "b"], 5) == 2
    assert required_keyword_hits(["a", "b", "c"], 1) == 1


def test_text_hash_target_matches_regardless_of_labels() -> None:
    text = "The PD model reports a Gini of 64%."
    target = RelevanceTarget(text_hash=text_fingerprint("the pd model  reports a gini of 64%."))
    assert target_matches(target, RetrievedItem(source="doc-x", section="chunk-3", text=text))
    assert not target_matches(target, RetrievedItem(source="doc-x", section="chunk-4", text="other"))


def test_judge_relevance_ref_and_keyword_targets() -> None:
    items = [
        RetrievedItem("CBUAE-MMG-2022", "Section 10 - Early Warning Systems", "quarterly reporting"),
        RetrievedItem("model.pdf", "Header", "Gini >= 0.40 is required"),
        RetrievedItem("CBUAE-MMG-2022", "Section 1 - Governance", "board"),
    ]
    targets = [
        RelevanceTarget(source="CBUAE-MMG-2022", section="Section 1"),
        RelevanceTarget(keywords=("Gini", "0.40")),
    ]
    relevances, matched = judge_relevance(items, targets)
    assert relevances == [0, 1, 1]
    assert matched == [[], [1], [0]]


def test_percentile_type7() -> None:
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 95) == 10
    assert percentile([], 50) is None
    assert percentile([1, 2, 3, 4, 5], 95) == pytest.approx(4.8)


def test_groundedness_bounds() -> None:
    assert groundedness("Gini coefficient", ["The Gini coefficient must be 0.40"]) == 1.0
    assert groundedness("banana smoothie", ["The Gini coefficient"]) == 0.0
    assert groundedness("the and of", ["anything"]) is None


def test_comma_numbers_stay_one_token() -> None:
    assert "1,250,000" in tokenize("Exposure of AED 1,250,000 at default")
    assert "1,250,000" in content_tokens("1,250,000 exposure")


def test_token_f1_and_coverage() -> None:
    assert token_f1("gini", "gini auc") == pytest.approx(0.6667, abs=1e-3)
    assert token_f1("psi", "gini auc") == 0.0
    assert token_f1("anything", "") is None
    assert question_coverage("minimum Gini coefficient", "The Gini coefficient is 0.40") == pytest.approx(2 / 3)


def test_score_normalisation() -> None:
    assert normalize_score("rerank_nvidia", 0) == 0.5
    assert normalize_score("rerank_nvidia", -1000) == pytest.approx(0.0)
    assert normalize_score("rerank_gemini", 7.5) == 0.75
    assert normalize_score("rrf", 1.4) == 1.0
    assert normalize_score("bm25", 12.3) is None
    assert normalize_score(None, 1.0) is None
    assert classify_score_kind("hybrid_rrf_reranked", "nvidia") == "rerank_nvidia"
    assert classify_score_kind("bm25_reranked", "gemini") == "rerank_gemini"
    assert classify_score_kind("dense_reranked", None) == "rerank"
    assert classify_score_kind("hybrid_rrf", None) == "rrf"
    assert classify_score_kind("bm25", None) == "bm25"
    assert classify_score_kind(None, None) is None


def test_inline_citations_and_token_estimate() -> None:
    answer = "Gini >= 0.40 [Source: CBUAE-MMG-2022, Section: Section 4] and AUC [source: x, Section: y]."
    assert count_inline_citations(answer) == 2
    assert count_inline_citations("no citations") == 0
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("") == 0


def test_rates_and_means() -> None:
    assert safe_rate(1, 0) is None
    assert safe_rate(1, 4) == 0.25
    assert mean_or_none([None, 1.0, 3.0]) == 2.0
    assert mean_or_none([None]) is None


def test_metric_curves_shapes() -> None:
    curves = metric_curves([(RELEVANCES, MATCHED, 2), ([1, 0, 0, 0], [[0], [], [], []], 1)], 4)
    assert curves["k"] == [1, 2, 3, 4]
    for key in ("hit", "recall", "precision", "ndcg"):
        assert len(curves[key]) == 4
        assert all(0.0 <= v <= 1.0 for v in curves[key])
    assert curves["hit"][0] == 0.5 and curves["hit"][1] == 1.0
    assert metric_curves([], 5) == {"k": [], "hit": [], "recall": [], "precision": [], "ndcg": []}
    assert not math.isnan(curves["ndcg"][3])
