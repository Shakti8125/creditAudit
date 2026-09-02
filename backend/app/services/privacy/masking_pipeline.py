from __future__ import annotations

from typing import Any

from app.services.privacy.bank_matcher import BankNameMatcher, get_bank_matcher
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.ner_masker import NERMasker, get_ner_masker


class MaskingPipeline:
    """Orchestrates the full zero-trust privacy masking flow.

    Extracts bank names and PII entities, resolves overlapping spans,
    and replaces entities using precise character offset slicing in reverse order.
    """

    def __init__(
        self,
        bank_matcher: BankNameMatcher | None = None,
        ner_masker: NERMasker | None = None,
    ) -> None:
        """Initializes the masking pipeline with bank matcher and NER masker instances."""
        self.bank_matcher = bank_matcher or get_bank_matcher()
        self.ner_masker = ner_masker or get_ner_masker()

    def mask_document(self, raw_text: str, registry: EntityRegistry | None = None) -> tuple[str, EntityRegistry]:
        """Masks sensitive entities in the document text using offset slicing.

        Args:
            raw_text: Original unmasked text.
            registry: Optional existing registry. If not provided, a new one is created.

        Returns:
            Tuple of (masked_text, registry).
        """
        if registry is None:
            registry = EntityRegistry()
        if not raw_text:
            return "", registry

        # 1. Run BankNameMatcher to collect bank spans
        bank_matches = self.bank_matcher.find_matches(raw_text)

        # 2. Run NERMasker to collect entity spans
        ner_matches = self.ner_masker.find_entities(raw_text)

        # Merge all spans into a unified list of dictionaries
        spans: list[dict[str, Any]] = []
        for start, end, text in bank_matches:
            spans.append({
                "start": start,
                "end": end,
                "text": text,
                "category": "BANK",
            })

        for ent in ner_matches:
            spans.append({
                "start": ent.start,
                "end": ent.end,
                "text": ent.text,
                "category": ent.category,
            })

        # 3. Resolve overlaps by choosing the longest match first.
        # Sort by span length descending, then by start index ascending.
        spans.sort(key=lambda s: (s["end"] - s["start"], -s["start"]), reverse=True)

        resolved_spans: list[dict[str, Any]] = []
        covered_indices: set[int] = set()

        for span in spans:
            span_indices = set(range(span["start"], span["end"]))
            if not span_indices.intersection(covered_indices):
                resolved_spans.append(span)
                covered_indices.update(span_indices)

        # 4. Sort resolved spans by start position in reverse order (descending)
        # to execute character offset slice replacements without index drift.
        resolved_spans.sort(key=lambda s: s["start"], reverse=True)

        # 5. Perform slice replacement on raw_text
        masked_text = raw_text
        for span in resolved_spans:
            token = registry.mask(span["text"], span["category"])
            masked_text = masked_text[: span["start"]] + token + masked_text[span["end"] :]

        # 6. Global regex pass to replace any remaining occurrences that NER missed
        import re
        mapping = registry.get_mapping()
        # Sort by length descending to replace longest entities first
        sorted_entities = sorted(mapping.keys(), key=len, reverse=True)
        for entity in sorted_entities:
            token = mapping[entity]
            pattern = rf"(?<!\w){re.escape(entity)}(?!\w)"
            masked_text = re.sub(pattern, token, masked_text)

        # 7. Return (masked_text, registry)
        return masked_text, registry

