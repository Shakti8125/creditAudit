from __future__ import annotations

import pytest
from app.services.privacy.bank_matcher import BankNameMatcher
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.ner_masker import NERMasker, EntitySpan
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError


def test_bank_matcher_word_boundaries_and_case():
    """Verify bank matcher matches exact banks and case-insensitively, but rejects substring false positives."""
    matcher = BankNameMatcher()

    # Substrings inside words should NOT match
    neg_text = "The FABRIC was high quality and the team felt CONFIDENT near the Gulfstream with ADCBXYZ."
    matches = matcher.find_matches(neg_text)
    assert len(matches) == 0, f"False positives detected on sub-words: {matches}"

    # True bank names should match
    pos_text = "Loans approved by FAB, Emirates NBD, and Mashreq Bank."
    matches = matcher.find_matches(pos_text)
    matched_names = [m[2] for m in matches]
    assert "FAB" in matched_names
    assert "Emirates NBD" in matched_names
    assert "Mashreq Bank" in matched_names

    # Half-open interval slicing check (Off-by-one verification PRV-05)
    for start, end, name in matches:
        extracted = pos_text[start:end]
        assert extracted.lower() == name.lower(), f"Slice mismatch: expected '{name}', got '{extracted}'"


def test_ner_masker_financial_protection():
    """Verify NERMasker protects financial numbers, currencies, dates, and ratios."""
    masker = NERMasker()

    test_samples = [
        ("AED 15.5 Million", True),
        ("USD 10,000,000", True),
        ("$2.4B", True),
        ("€500k", True),
        ("1,250,000", True),
        ("42%", True),
        ("12.5 %", True),
        ("45 bps", True),
        ("50 basis points", True),
        ("1.25x", True),
        ("0.78", True),
        ("2024-12-31", True),
        ("31 December 2023", True),
        ("December 31, 2023", True),
        ("FY2024", True),
        ("Q1 2024", True),
        ("H1 2023", True),
    ]

    for sample, expected in test_samples:
        protected = masker._is_protected(sample)
        assert protected == expected, f"Failed protection check for '{sample}': got {protected}"


def test_masking_pipeline_longest_match_and_offset_slicing():
    """Verify longest match resolution and offset-based reverse slicing prevents token corruption."""
    pipeline = MaskingPipeline()

    text = (
        "First Abu Dhabi Bank (FAB) issued a facility to AlphaCorp Holdings Limited "
        "and AlphaCorp. The manager Will Smith said: 'Will the credit policy apply in May?' "
        "The loan was AED 2,500,000 with 75 bps margin."
    )

    masked_text, registry = pipeline.mask_document(text)

    # Verify no nested bracket corruptions
    assert "[[" not in masked_text
    assert "]]" not in masked_text

    # Verify unmasking returns verbatim raw text
    unmasked = registry.unmask_text(masked_text)
    assert unmasked == text, f"Unmasking corrupted text!\nOriginal: {text}\nUnmasked: {unmasked}"


def test_egress_validator_catches_registered_entities():
    """Verify EgressValidator blocks leaks of entities in the registry mapping."""
    validator = EgressValidator()
    registry = EntityRegistry()
    token = registry.mask("SecretBank", "BANK")

    # Clean text with valid token should pass
    clean_text = f"The loan was provided by {token}."
    report = validator.validate(clean_text, registry)
    assert report.is_clean is True

    dirty_text = "The loan was provided by SecretBank."
    with pytest.raises(EgressViolationError) as exc_info:
        validator.validate(dirty_text, registry)
    assert any("Registered entity leak detected" in v for v in exc_info.value.report.violations)


def test_egress_validator_allows_valid_bracket_tokens():
    """Verify EgressValidator does NOT flag valid bracket tokens ([ORG_1], [BANK_1]) as leaks."""
    validator = EgressValidator()
    registry = EntityRegistry()

    valid_masked_text = (
        "On [DATE_1], [BANK_1] and [ORG_1] approved a loan for [PERSON_1]. "
        "The exposure was AED 1,000,000 at 50 bps."
    )
    report = validator.validate(valid_masked_text, registry)
    assert report.is_clean is True
    assert len(report.violations) == 0


def test_atomic_unmasking_with_special_characters():
    """Verify unmasking with entities containing parentheses, dots, dashes and symbols."""
    registry = EntityRegistry()
    t1 = registry.mask("Dr. John Smith-Doe, Jr. (Ph.D.)", "PERSON")
    t2 = registry.mask("Mega-Corp & Sons Ltd.", "ORG")
    t3 = registry.mask("contact+audit@model-ai.ae", "EMAIL")

    masked = f"Report for {t1} at {t2}. Inquiries to {t3}."
    unmasked = registry.unmask_text(masked)
    expected = "Report for Dr. John Smith-Doe, Jr. (Ph.D.) at Mega-Corp & Sons Ltd.. Inquiries to contact+audit@model-ai.ae."
    assert unmasked == expected


def test_egress_validator_word_boundary_no_false_positive_on_subwords():
    """Verify regex word boundaries prevent false-positive egress violations on common substrings."""
    validator = EgressValidator()
    registry = EntityRegistry()

    # Register entities that are common substrings of normal words
    registry.mask("Mark", "PERSON")
    registry.mask("Dan", "PERSON")
    registry.mask("Ali", "PERSON")

    # Texts containing "Market", "Standard", "Validation" should NOT trigger false positive
    clean_text = "The Market analysis follows the Standard validation framework."
    report = validator.validate(clean_text, registry)
    assert report.is_clean is True
    assert len(report.violations) == 0

    # True leak of "Mark" or "Dan" as a standalone word MUST trigger violation
    leak_text = "Audit performed by Mark at the branch."
    with pytest.raises(EgressViolationError) as exc_info:
        validator.validate(leak_text, registry)
    assert any("Mark" in v for v in exc_info.value.report.violations)


def test_ner_masker_expanded_banking_metrics():
    """Verify expanded banking and credit risk metrics are protected from masking."""
    masker = NERMasker()

    metrics = [
        "gini",
        "auc",
        "ks",
        "psi",
        "brier",
        "car",
        "ead",
        "lgd",
        "pd",
        "npl",
        "raroc",
        "var",
        "wacc",
        "nim",
        "cet1",
        "NPL",
        "RAROC",
        "VaR",
        "WACC",
        "NIM",
        "CET1",
    ]

    for metric in metrics:
        assert masker._is_protected(metric) is True, f"Banking metric '{metric}' was not protected!"


def test_ner_masker_skips_valid_tokens():
    """Verify valid replacement tokens are protected and not re-masked by NERMasker."""
    masker = NERMasker()

    valid_tokens = [
        "[BANK_1]",
        "[ORG_2]",
        "[PERSON_3]",
        "[EMAIL_4]",
        "[PHONE_5]",
        "[GPE_6]",
        "[LOC_7]",
        "[PRODUCT_8]",
        "[SYSTEM_9]",
        "[METRIC_10]",
    ]

    for token in valid_tokens:
        assert masker._is_protected(token) is True, f"Valid token '{token}' was not protected!"

    # find_entities should not extract valid tokens as entities
    sample_text = "The review for [ORG_1] and [BANK_2] was conducted by [PERSON_3]."
    entities = masker.find_entities(sample_text)
    extracted_texts = [e.text for e in entities]
    for token in ["[ORG_1]", "[BANK_2]", "[PERSON_3]"]:
        assert token not in extracted_texts, f"Valid token '{token}' was re-extracted as entity: {extracted_texts}"


def test_privacy_schemas_pydantic_v2():
    """Verify Pydantic v2 schemas and ConfigDict(from_attributes=True) functionality."""
    import uuid
    from app.schemas.privacy import MaskRequest, MaskResponse, RedactionLogResponse

    req_id = uuid.uuid4()
    req = MaskRequest(text="Sample bank text", session_id=req_id)
    assert req.text == "Sample bank text"
    assert req.session_id == req_id

    resp = MaskResponse(masked_text="[BANK_1]", redactions={"FAB": "[BANK_1]"})
    assert resp.masked_text == "[BANK_1]"
    assert resp.redactions["FAB"] == "[BANK_1]"

    log_resp = RedactionLogResponse(session_id=req_id, redactions={"FAB": "[BANK_1]"})
    assert log_resp.session_id == req_id
    assert log_resp.redactions["FAB"] == "[BANK_1]"

