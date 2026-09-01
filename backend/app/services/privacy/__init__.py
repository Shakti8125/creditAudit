"""Zero-trust privacy and entity masking services."""

from __future__ import annotations

from app.services.privacy.bank_matcher import BankNameMatcher, get_bank_matcher
from app.services.privacy.egress_validator import (
    EgressReport,
    EgressValidator,
    EgressViolationError,
)
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.ner_masker import EntitySpan, NERMasker, get_ner_masker

__all__ = [
    "BankNameMatcher",
    "get_bank_matcher",
    "EgressReport",
    "EgressValidator",
    "EgressViolationError",
    "EntityRegistry",
    "MaskingPipeline",
    "EntitySpan",
    "NERMasker",
    "get_ner_masker",
]
