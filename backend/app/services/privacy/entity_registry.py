from __future__ import annotations

import re


class EntityRegistry:
    """In-memory bijective mapping for entity tokens (session-scoped).

    Never persisted to disk or DB. Maps sensitive entities to bracket tokens
    (e.g., 'Emirates NBD' -> '[BANK_1]') and provides atomic restoration.
    """

    def __init__(self) -> None:
        """Initializes the forward and reverse token maps and category counters."""
        self._forward: dict[str, str] = {}
        self._reverse: dict[str, str] = {}
        self._counters: dict[str, int] = {
            "BANK": 1,
            "ORG": 1,
            "PERSON": 1,
            "EMAIL": 1,
            "PHONE": 1,
            "GPE": 1,
            "LOC": 1,
            "PRODUCT": 1,
            "SYSTEM": 1,
            "METRIC": 1,
        }

    def mask(self, entity: str, category: str) -> str:
        """Returns existing token if entity exists, else creates a new one (e.g., `[BANK_1]`).

        Strips leading and trailing whitespace and returns an empty string if the entity is empty.

        Args:
            entity: The raw entity string to mask.
            category: Entity category (e.g., 'BANK', 'ORG', 'PERSON').

        Returns:
            The assigned masking token or empty string if input was empty.
        """
        cleaned_entity = entity.strip()
        if not cleaned_entity:
            return ""

        if cleaned_entity in self._forward:
            return self._forward[cleaned_entity]

        if category not in self._counters:
            self._counters[category] = 1

        count = self._counters[category]
        token = f"[{category}_{count}]"
        self._counters[category] += 1

        self._forward[cleaned_entity] = token
        self._reverse[token] = cleaned_entity
        return token

    def unmask_text(self, masked_text: str) -> str:
        """Replaces tokens with original entities atomically in a single pass.

        Uses length-descending regex alternation to avoid prefix collisions
        (e.g., replacing [ORG_10] before [ORG_1]) and prevents sequential substitution corruption.

        Args:
            masked_text: Text containing masking tokens.

        Returns:
            Text with all known tokens replaced with their original entities.
        """
        if not masked_text or not self._reverse:
            return masked_text

        # Sort tokens by length descending to match longer tokens first in regex
        sorted_tokens = sorted(self._reverse.keys(), key=len, reverse=True)
        pattern = re.compile("|".join(re.escape(token) for token in sorted_tokens))
        return pattern.sub(lambda match: self._reverse[match.group(0)], masked_text)

    def get_mapping(self) -> dict[str, str]:
        """Returns a copy of the forward mapping for the masking inspector UI."""
        return self._forward.copy()

    def get_reverse_mapping(self) -> dict[str, str]:
        """Returns a copy of the reverse mapping."""
        return self._reverse.copy()

