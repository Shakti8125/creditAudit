"""Document aliases (``DOC-n``) and their protection in the masking pipeline (QA-004)."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

from app.schemas.retrieval import Citation
from app.services.evaluation.prompts import format_context
from app.services.privacy.doc_alias import (
    DOC_ALIAS_PATTERN,
    apply_doc_aliases,
    assign_doc_aliases,
    doc_source,
    expand_aliases,
)
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.ner_masker import EntitySpan, get_ner_masker

DOC_A = str(uuid.uuid4())
DOC_B = str(uuid.uuid4())


def _citation(document_id: str | None, text: str = "text", section: str = "Sec", source: str | None = None, alias: str | None = None) -> Citation:
    return Citation(
        source=source or (doc_source(document_id) if document_id else "CBUAE-MMG-2022"),
        section=section,
        text=text,
        score=1.0,
        retrieval_method="bm25",
        document_id=document_id,
        alias=alias,
    )


# ---------------------------------------------------------------------------- alias assignment


def test_alias_pattern_matches_aliases_and_not_document_ids() -> None:
    for text in ("DOC-1", "doc-12", "[Source: DOC-2, Section: X]", "see DOC-3."):
        assert DOC_ALIAS_PATTERN.search(text), text
    for text in (f"doc-{uuid.uuid4()}", "DOC-1234", "ADOC-1", "DOC-1-2", "DOC-"):
        assert DOC_ALIAS_PATTERN.search(text) is None, text


def test_primary_document_is_doc_1_and_the_rest_follow_in_order() -> None:
    citations = [_citation(DOC_B), _citation(None), _citation(DOC_A), _citation(DOC_B)]

    assert assign_doc_aliases(citations, DOC_A) == {DOC_A: "DOC-1", DOC_B: "DOC-2"}
    assert assign_doc_aliases(citations) == {DOC_B: "DOC-1", DOC_A: "DOC-2"}
    assert assign_doc_aliases([_citation(None)], DOC_A) == {DOC_A: "DOC-1"}
    assert assign_doc_aliases([_citation(None)]) == {}
    # Deterministic for the same input.
    assert assign_doc_aliases(citations, DOC_A) == assign_doc_aliases(citations, DOC_A)


def test_apply_doc_aliases_labels_documents_only() -> None:
    aliased = apply_doc_aliases([_citation(DOC_A), _citation(None)], {DOC_A: "DOC-1"})
    assert [c.alias for c in aliased] == ["DOC-1", None]


def test_expand_aliases_is_for_display_only_and_case_insensitive() -> None:
    names = {"DOC-1": "model_validation.pdf"}
    assert expand_aliases("See [Source: DOC-1, Section: A] and doc-1 and DOC-2.", names) == (
        "See [Source: model_validation.pdf, Section: A] and model_validation.pdf and DOC-2."
    )
    assert expand_aliases("DOC-1", {}) == "DOC-1"


# ---------------------------------------------------------------------------- the context block


def test_context_labels_documents_with_aliases_and_never_with_their_identity() -> None:
    filename = "Emirates NBD PD Validation.pdf"
    citations = [
        _citation(DOC_A, text="Gini 64%", section="Power", source=filename),  # even a stale raw source
        _citation(None, text="Gini >= 0.40", section="Section 4"),
    ]
    context = format_context(citations, primary_document_id=DOC_A)

    assert "Source: DOC-1\nSection: Power\nContent: Gini 64%" in context
    assert "Source: CBUAE-MMG-2022\nSection: Section 4\nContent: Gini >= 0.40" in context
    assert filename not in context and DOC_A not in context


def test_context_keeps_aliases_assigned_by_the_caller() -> None:
    cited = apply_doc_aliases([_citation(DOC_B), _citation(DOC_A)], {DOC_A: "DOC-1", DOC_B: "DOC-2"})
    context = format_context(cited)
    assert context.index("Source: DOC-2") < context.index("Source: DOC-1")


def test_registry_substitution_touches_public_text_only() -> None:
    registry = EntityRegistry()
    registry.mask("Acme Bank", "ORG")
    citations = [
        _citation(None, text="Acme Bank must keep a Gini of 0.40.", section="Acme Bank rules"),
        _citation(DOC_A, text="Acme Bank reports a Gini of 0.64."),
    ]

    context = format_context(citations, registry=registry, primary_document_id=DOC_A)

    assert "[ORG_1] must keep a Gini of 0.40." in context
    assert "Section: [ORG_1] rules" in context
    # Tenant text is never rewritten here: a raw entity in it stays visible to the egress check.
    assert "Acme Bank reports a Gini of 0.64." in context


# ---------------------------------------------------------------------------- registry helpers


def test_registry_clone_is_independent() -> None:
    registry = EntityRegistry()
    registry.mask("Acme Bank", "ORG")
    copy = registry.clone()
    copy.mask("Beta Bank", "ORG")

    assert registry.get_mapping() == {"Acme Bank": "[ORG_1]"}
    assert copy.get_mapping() == {"Acme Bank": "[ORG_1]", "Beta Bank": "[ORG_2]"}
    assert registry.mask("Gamma Bank", "ORG") == "[ORG_2]"  # counters are copied, not shared


def test_registry_apply_to_text_prefers_the_longest_entity_on_word_boundaries() -> None:
    registry = EntityRegistry()
    registry.mask("Acme", "ORG")
    registry.mask("Acme Capital Partners", "ORG")

    out = registry.apply_to_text("Acme Capital Partners and Acme, not Acmeville.")

    assert out == "[ORG_2] and [ORG_1], not Acmeville."
    assert registry.apply_to_text("") == "" and EntityRegistry().apply_to_text("Acme") == "Acme"


# ---------------------------------------------------------------------------- masking never registers an alias


class _FakeBanks:
    def find_matches(self, text: str) -> list[tuple[int, int, str]]:
        return []


class _FakeNer:
    """Reports every ``DOC-n`` and ``DOC-n Acme Corp`` it sees as an ORG, like a noisy tagger."""

    def find_entities(self, text: str) -> list[EntitySpan]:
        return [
            EntitySpan(m.start(), m.end(), m.group(0), "ORG")
            for m in re.finditer(r"DOC-\d+(?: Acme Corp)?", text)
        ]


def _pipeline() -> MaskingPipeline:
    banks: Any = _FakeBanks()
    ner: Any = _FakeNer()
    return MaskingPipeline(bank_matcher=banks, ner_masker=ner)


def test_an_alias_is_never_registered_as_an_entity() -> None:
    text = "[Source: DOC-1, Section: Calibration] and again DOC-2."
    masked, registry = _pipeline().mask_document(text)
    assert masked == text
    assert registry.get_mapping() == {}


def test_an_entity_next_to_an_alias_is_still_masked() -> None:
    masked, registry = _pipeline().mask_document("As DOC-1 Acme Corp reported, DOC-1 holds.")
    assert masked == "As DOC-1 [ORG_1] reported, DOC-1 holds."
    assert registry.get_mapping() == {"Acme Corp": "[ORG_1]"}


def test_real_masker_protects_aliases_but_not_names() -> None:
    masker = get_ner_masker()
    assert masker._is_protected("DOC-1") and masker._is_protected("doc-12")
    assert not masker._is_protected("DOC-1 Acme Capital")
    masked, registry = MaskingPipeline().mask_document(
        "According to DOC-1 and DOC-2 the model is stable; Emirates NBD reviewed DOC-1."
    )
    assert "DOC-1" in masked and "DOC-2" in masked and "Emirates NBD" not in masked
    assert set(registry.get_mapping()) == {"Emirates NBD"}


@pytest.mark.parametrize(
    ("filename", "hidden"),
    [
        ("qa_synthetic_pd_validation_v1.pdf", "qa_synthetic_pd_validation_v1.pdf"),
        ("Emirates NBD PD Validation v1.pdf", "Emirates NBD"),
    ],
)
def test_a_filename_in_an_answer_is_registered_but_an_alias_is_not(filename: str, hidden: str) -> None:
    masked, registry = MaskingPipeline().mask_document(
        f"The Gini is 64% [Source: {filename}, Section: Power] and [Source: DOC-1, Section: Power]."
    )
    assert hidden not in masked and hidden in registry.get_mapping()
    assert "[Source: DOC-1, Section: Power]" in masked
    assert not any(DOC_ALIAS_PATTERN.fullmatch(entity) for entity in registry.get_mapping())
