from __future__ import annotations

import pytest

from app.services.evaluation.default_dataset import DEFAULT_CASE_SPECS, build_expected_refs
from app.services.evaluation.metrics import keyword_hits, required_keyword_hits
from app.services.guardrails.checks import run_input_guardrails
from app.services.retrieval.hybrid_retriever import CBUAE_REGULATORY_CORPUS


def test_22_specs_with_unique_keys() -> None:
    assert len(DEFAULT_CASE_SPECS) == 22
    assert len({spec.key for spec in DEFAULT_CASE_SPECS}) == 22


def test_section_indices_are_valid() -> None:
    for spec in DEFAULT_CASE_SPECS:
        assert spec.targets
        for target in spec.targets:
            assert 0 <= target.section_index < len(CBUAE_REGULATORY_CORPUS)


def test_keywords_hit_own_section_and_no_other() -> None:
    for spec in DEFAULT_CASE_SPECS:
        for target in spec.targets:
            needed = required_keyword_hits(target.keywords, None)
            for idx, item in enumerate(CBUAE_REGULATORY_CORPUS):
                hits = keyword_hits(item["text"], target.keywords)
                if idx == target.section_index:
                    assert hits >= needed, (spec.key, idx)
                else:
                    assert hits < needed, (spec.key, idx)


def test_multi_target_cases_exist() -> None:
    assert sum(1 for spec in DEFAULT_CASE_SPECS if len(spec.targets) > 1) == 2


def test_build_expected_refs_uses_corpus_labels() -> None:
    for spec in DEFAULT_CASE_SPECS:
        refs = build_expected_refs(spec)
        assert len(refs) == len(spec.targets)
        for ref, target in zip(refs, spec.targets):
            assert ref["source"] == "CBUAE-MMG-2022"
            assert ref["section"] == CBUAE_REGULATORY_CORPUS[target.section_index]["section"]
            assert ref["keywords"] == list(target.keywords)
            assert ref["min_keyword_hits"] is None and ref["chunk_index"] is None


@pytest.mark.asyncio
async def test_default_questions_pass_input_guardrails() -> None:
    for spec in DEFAULT_CASE_SPECS:
        assert await run_input_guardrails(spec.question, check_off_topic=False) is None, spec.key
