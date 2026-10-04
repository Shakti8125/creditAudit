from __future__ import annotations

from typing import Any

from app.services.privacy.bank_matcher import BankNameMatcher, get_bank_matcher
from app.services.privacy.doc_alias import DOC_ALIAS_PATTERN
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.ner_masker import NERMasker, get_ner_masker

# Characters trimmed from the edges of a span left over after an alias is cut out.
_SPAN_EDGE_CHARS = " \t\r\n,;:.-()[]\"'"


def _exclude_doc_aliases(raw_text: str, spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cut ``DOC-n`` aliases out of the detected entity spans.

    A span that is just an alias is dropped. A span that merely contains one
    (``"DOC-1 Acme Corp"``) keeps its other parts, so a real entity next to an
    alias is still masked.

    Args:
        raw_text: The text the spans were detected in.
        spans: Detected spans (``start``, ``end``, ``text``, ``category``).

    Returns:
        The spans without any alias characters.
    """
    aliases = [(m.start(), m.end()) for m in DOC_ALIAS_PATTERN.finditer(raw_text)]
    if not aliases:
        return spans

    kept: list[dict[str, Any]] = []
    for span in spans:
        pieces = [(span["start"], span["end"])]
        for a_start, a_end in aliases:
            remaining: list[tuple[int, int]] = []
            for p_start, p_end in pieces:
                if a_end <= p_start or a_start >= p_end:
                    remaining.append((p_start, p_end))
                    continue
                if p_start < a_start:
                    remaining.append((p_start, a_start))
                if a_end < p_end:
                    remaining.append((a_end, p_end))
            pieces = remaining
        for p_start, p_end in pieces:
            if (p_start, p_end) == (span["start"], span["end"]):
                kept.append(span)
                continue
            piece = raw_text[p_start:p_end]
            trimmed = piece.strip(_SPAN_EDGE_CHARS)
            if sum(ch.isalnum() for ch in trimmed) < 2:
                continue
            start = p_start + piece.find(trimmed)
            kept.append({**span, "start": start, "end": start + len(trimmed), "text": trimmed})
    return kept


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

        # Document aliases (DOC-1) are content-free labels, never entities: a
        # registered alias would trip the egress check on the next prompt (QA-004).
        spans = _exclude_doc_aliases(raw_text, spans)

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
        masked_text = registry.apply_to_text(masked_text)

        # 7. Return (masked_text, registry)
        return masked_text, registry

