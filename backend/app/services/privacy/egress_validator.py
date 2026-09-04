from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.privacy.bank_matcher import BankNameMatcher, get_bank_matcher
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.ner_masker import NERMasker, get_ner_masker

# Regex to recognize valid privacy replacement tokens
VALID_TOKEN_PATTERN = re.compile(
    r"^\[?(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]?$"
)


@dataclass
class EgressReport:
    """Report detailing whether masked text passed egress validation and any detected leaks."""

    is_clean: bool
    violations: list[str]


class EgressViolationError(Exception):
    """Raised when unmasked sensitive entities or bank names are detected in egress text."""

    def __init__(self, message: str, report: EgressReport) -> None:
        super().__init__(message)
        self.report = report


class EgressValidator:
    """Validates that no unmasked entities leak to the LLM.

    Runs as a final check before data leaves the system.
    """

    def __init__(
        self,
        bank_matcher: BankNameMatcher | None = None,
        ner_masker: NERMasker | None = None,
    ) -> None:
        """Initializes the egress validator with injected or singleton matcher instances."""
        self.bank_matcher = bank_matcher or get_bank_matcher()
        self.ner_masker = ner_masker or get_ner_masker()

    def validate(self, masked_text: str, registry: EntityRegistry | None = None) -> EgressReport:
        """Validates that masked_text does not contain sensitive unmasked entities.

        Args:
            masked_text: Text that has undergone masking.
            registry: Optional entity registry containing mapped original entities.

        Returns:
            EgressReport with is_clean status and any violations.

        Raises:
            EgressViolationError: If violations are found.
        """
        violations: list[str] = []

        if not masked_text:
            return EgressReport(is_clean=True, violations=[])

        # 1. Check registered original entity strings from registry mapping (PRV-02)
        # Use regex word boundaries (?<!\w)...(?!\w) instead of naive substring matching
        # to prevent false-positive egress violations on common sub-words (e.g. 'Mark' in 'Market', 'Dan' in 'Standard').
        if registry is not None:
            mapping = registry.get_mapping()
            for original_entity in mapping.keys():
                if original_entity:
                    pattern = rf"(?<!\w){re.escape(original_entity)}(?!\w)"
                    if re.search(pattern, masked_text):
                        violations.append(f"Registered entity leak detected: '{original_entity}'")

        # 2. Re-run BankNameMatcher on the masked text (should find 0 matches)
        bank_matches = self.bank_matcher.find_matches(masked_text)
        for _, _, text in bank_matches:
            violations.append(f"Bank name leak detected: {text}")

        # 3. Re-run NERMasker on the masked text (PRV-03: exclude valid tokens)
        ner_matches = self.ner_masker.find_entities(masked_text)
        for ent in ner_matches:
            if ent.category in ("ORG", "PERSON", "EMAIL", "PHONE", "GPE", "LOC", "BANK", "PRODUCT", "SYSTEM", "METRIC"):
                # Exclude valid bracket masking tokens (even if sliced or adjacent to text/punctuation)
                if VALID_TOKEN_PATTERN.match(ent.text.strip()) or re.search(
                    r"\[?(?:BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]?", ent.text
                ):
                    continue
                violations.append(f"{ent.category} leak detected: {ent.text}")

        is_clean = len(violations) == 0
        report = EgressReport(is_clean=is_clean, violations=violations)

        # CRITICAL: If the report is not clean, the request MUST be blocked
        if not is_clean:
            raise EgressViolationError(
                f"Privacy egress validation failed with {len(violations)} violations.",
                report=report,
            )

        return report

