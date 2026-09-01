from __future__ import annotations

import json
from pathlib import Path

import ahocorasick

RESOURCE_PATH = Path(__file__).parent / "resources" / "gcc_bank_names.json"


class BankNameMatcher:
    """Finds bank names in text using an Aho-Corasick automaton.

    Supports case-insensitive matching and enforces word boundary checks to avoid
    substring false positives on short bank abbreviations (e.g., 'FAB', 'CBD', 'DIB', 'Gulf').
    """

    def __init__(self, resource_path: Path | str | None = None) -> None:
        """Initializes the automaton and loads bank names from the resource file.

        Args:
            resource_path: Optional custom path to bank names JSON file.
        """
        self.resource_path = Path(resource_path) if resource_path else RESOURCE_PATH
        self._automaton = ahocorasick.Automaton()
        self._load_bank_names()
        self._automaton.make_automaton()

    def _load_bank_names(self) -> None:
        """Loads bank names into the Aho-Corasick automaton using lowercase keys."""
        if not self.resource_path.exists():
            raise FileNotFoundError(f"Bank names resource not found: {self.resource_path}")

        with open(self.resource_path, "r", encoding="utf-8") as f:
            bank_names: list[str] = json.load(f)

        for name in bank_names:
            clean_name = name.strip()
            if clean_name:
                self._automaton.add_word(clean_name.lower(), clean_name)

    def find_matches(self, text: str) -> list[tuple[int, int, str]]:
        """Returns a list of (start_index, end_index, matched_name) for all matches.

        Uses half-open intervals [start_index, end_index) and enforces word boundaries.
        Matches are case-insensitive, returning the exact matched substring from original text.

        Args:
            text: Input document text to scan.

        Returns:
            List of tuples: (start_index, end_index, matched_text).
        """
        if not text:
            return []

        text_lower = text.lower()
        matches: list[tuple[int, int, str]] = []
        for end_char_index, canonical_name in self._automaton.iter(text_lower):
            end_index = end_char_index + 1
            start_index = end_index - len(canonical_name)

            # Word boundary checks: neither preceding nor following character may be alphanumeric
            if start_index > 0 and text[start_index - 1].isalnum():
                continue
            if end_index < len(text) and text[end_index].isalnum():
                continue

            matched_text = text[start_index:end_index]
            matches.append((start_index, end_index, matched_text))

        return matches


_default_bank_matcher: BankNameMatcher | None = None


def get_bank_matcher() -> BankNameMatcher:
    """Returns a module-level singleton instance of BankNameMatcher."""
    global _default_bank_matcher
    if _default_bank_matcher is None:
        _default_bank_matcher = BankNameMatcher()
    return _default_bank_matcher

