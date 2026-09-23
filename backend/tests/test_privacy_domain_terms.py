from __future__ import annotations

import pytest

from app.services.privacy.ner_masker import get_ner_masker


@pytest.fixture(scope="module")
def masker():
    return get_ner_masker()


@pytest.mark.parametrize(
    "text",
    [
        "the Board Risk Committee",
        "Board Risk Committee",
        "CBUAE",
        "CBUAE MMG",
        "ECL",
        "SICR",
        "ECL/SICR",
        "UAE",
        "IFRS 9",
        "Kolmogorov-Smirnov",
    ],
)
def test_regulatory_vocabulary_is_not_treated_as_an_entity(masker, text: str) -> None:
    assert masker._is_protected(text) is True


@pytest.mark.parametrize("text", ["Emirates NBD", "John Smith", "Acme Holdings", "Board Bank"])
def test_real_names_are_still_maskable(masker, text: str) -> None:
    assert masker._is_protected(text) is False


def test_regulatory_question_with_corpus_context_passes_egress() -> None:
    """Regression: "CBUAE" in a question was masked to [ORG_1] while the retrieved
    corpus still said "CBUAE", so the final-prompt egress check blocked every answer."""
    from app.services.privacy.egress_validator import EgressValidator
    from app.services.privacy.masking_pipeline import MaskingPipeline
    from app.services.retrieval.hybrid_retriever import CBUAE_REGULATORY_CORPUS

    question = (
        "Summarise the PD model validation requirements in the CBUAE MMG and what the "
        "Board Risk Committee must approve for SICR and ECL staging at Emirates NBD."
    )
    masked_question, registry = MaskingPipeline().mask_document(question)
    assert "CBUAE" in masked_question and "SICR" in masked_question and "ECL" in masked_question
    assert "Emirates NBD" not in masked_question  # real bank names are still masked

    context = "\n\n".join(f"Source: {c['source']}\nSection: {c['section']}\nContent: {c['text']}" for c in CBUAE_REGULATORY_CORPUS)
    prompt = f"Context:\n{context}\n\nQuestion: {masked_question}"
    EgressValidator().validate(prompt, registry)  # must not raise


def test_default_eval_questions_have_no_false_positive_entities(masker) -> None:
    from app.services.evaluation.default_dataset import DEFAULT_CASE_SPECS

    offenders = {
        (spec.key, e.text) for spec in DEFAULT_CASE_SPECS for e in masker.find_entities(spec.question)
    }
    assert offenders == set()
