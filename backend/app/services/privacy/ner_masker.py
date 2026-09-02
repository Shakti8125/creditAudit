from __future__ import annotations

import re
from dataclasses import dataclass

import spacy
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import SpacyNlpEngine


# Regex to recognize valid privacy replacement tokens to prevent re-masking
VALID_TOKEN_PATTERN = re.compile(
    r"^\[?(BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]?$"
)


@dataclass
class EntitySpan:
    """Represents an extracted entity span with start/end character offsets."""

    start: int
    end: int
    text: str
    category: str


class NERMasker:
    """Extracts PII and sensitive entities using spaCy and Presidio.

    Protects financial numbers, dates, currencies, ratios, and banking metrics from being masked.
    """

    FINANCIAL_PATTERNS = [
        # 1. Currency amounts: AED 15.5 Million, $2.4B, USD 10,000,000, SAR 500k, QAR 1.2M, etc.
        re.compile(
            r"(?:\b(?:AED|SAR|QAR|KWD|BHD|OMR|USD|EUR|GBP)|\$|€|£|¥)\s*\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:[Mm]illion|[Bb]illion|[Tt]rillion|[Tt]housand|[KkMmBbTt])?(?!\w)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:AED|SAR|QAR|KWD|BHD|OMR|USD|EUR|GBP|\$|€|£|¥)(?!\w)",
            re.IGNORECASE,
        ),
        # 2. Formatted numbers with commas: 1,250,000 or 100,000.50
        re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"),
        # 3. Percentages and basis points: 42%, 12.5 %, 45 bps, 50 basis points
        re.compile(
            r"\b\d+(?:\.\d+)?\s*(?:%|percent|percentage|bps|bp|basis\s+points?)(?!\w)",
            re.IGNORECASE,
        ),
        # 4. Ratios and multipliers: 1.25x, 0.78, 2.5X
        re.compile(r"\b\d+(?:\.\d+)?\s*[xX](?!\w)"),
        re.compile(r"\b0\.\d+\b"),
        # 5. ISO and standard dates: 2024-12-31, 31/12/2023, 12-31-2023
        re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b"),
        re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b"),
        # 6. Named dates: 31 December 2023, December 31, 2023
        re.compile(
            r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{2,4}\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}\b",
            re.IGNORECASE,
        ),
        # 7. Fiscal quarters and years: FY2024, FY24, Q1 2024, 2024-Q3, H1 2023
        re.compile(r"\b(?:FY|Q[1-4]|H[1-2])\s*[-/]?\s*\d{2,4}\b", re.IGNORECASE),
        re.compile(r"\b\d{4}\s*[-/]?\s*Q[1-4]\b", re.IGNORECASE),
    ]

    PROTECTED_CURRENCY_CODES = {
        "aed",
        "sar",
        "qar",
        "kwd",
        "bhd",
        "omr",
        "usd",
        "eur",
        "gbp",
    }

    # Expanded banking/credit risk metrics that should never be masked as PII/entities
    PROTECTED_METRIC_NAMES = {
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
    }

    def __init__(self, nlp: spacy.Language | None = None) -> None:
        """Initializes spaCy and Presidio AnalyzerEngine sharing the spaCy instance.

        Args:
            nlp: Optional pre-loaded spaCy Language model.

        Raises:
            RuntimeError: If 'en_core_web_lg' model is not installed.
        """
        if nlp is not None:
            self.nlp = nlp
        else:
            try:
                self.nlp = spacy.load("en_core_web_lg")
            except OSError as exc:
                raise RuntimeError(
                    "spaCy model 'en_core_web_lg' is not installed. "
                    "Please install it before running: python -m spacy download en_core_web_lg"
                ) from exc

        # Share the loaded spaCy model with Presidio AnalyzerEngine to avoid duplicate memory allocation
        spacy_engine = SpacyNlpEngine(models=[{"lang_code": "en", "model_name": "en_core_web_lg"}])
        spacy_engine.nlp = {"en": self.nlp}

        self.analyzer = AnalyzerEngine(
            nlp_engine=spacy_engine,
            default_score_threshold=0.6,
            supported_languages=["en"],
        )

    def _is_protected(self, text: str) -> bool:
        """Check if the text matches any financial patterns or valid tokens that must not be masked.

        Args:
            text: Entity text snippet to inspect.

        Returns:
            True if text matches financial/date/currency patterns or valid tokens, False otherwise.
        """
        cleaned = text.strip()
        if not cleaned:
            return False
        # Do not mask already valid bracket masking tokens (e.g., [BANK_1], [ORG_1])
        if VALID_TOKEN_PATTERN.match(cleaned):
            return True
        cleaned_lower = cleaned.lower()
        if (
            cleaned_lower in self.PROTECTED_CURRENCY_CODES
            or cleaned_lower in self.PROTECTED_METRIC_NAMES
        ):
            return True
        for pattern in self.FINANCIAL_PATTERNS:
            if pattern.search(cleaned):
                return True
        return False

    def find_entities(self, text: str) -> list[EntitySpan]:
        """Extracts ORG, PERSON, GPE via spaCy and EMAIL, PHONE via Presidio.

        Args:
            text: Input document text.

        Returns:
            List of EntitySpan instances representing detected entities.
        """
        if not text:
            return []

        entities: list[EntitySpan] = []

        # 1. Extract ORG, PERSON, GPE via spaCy
        doc = self.nlp(text)
        for ent in doc.ents:
            if ent.label_ in ("ORG", "PERSON", "GPE"):
                # Skip valid replacement tokens to prevent spaCy re-masking
                if VALID_TOKEN_PATTERN.match(ent.text.strip()):
                    continue
                if not self._is_protected(ent.text):
                    entities.append(
                        EntitySpan(
                            start=ent.start_char,
                            end=ent.end_char,
                            text=ent.text,
                            category=ent.label_,
                        )
                    )

        # 2. Extract EMAIL_ADDRESS, PHONE_NUMBER via Presidio AnalyzerEngine
        results = self.analyzer.analyze(
            text=text,
            entities=["EMAIL_ADDRESS", "PHONE_NUMBER"],
            language="en",
            score_threshold=0.6,
        )
        for res in results:
            span_text = text[res.start:res.end]
            # Skip valid replacement tokens to prevent Presidio re-masking
            if VALID_TOKEN_PATTERN.match(span_text.strip()):
                continue
            if not self._is_protected(span_text):
                category = "EMAIL" if res.entity_type == "EMAIL_ADDRESS" else "PHONE"
                entities.append(
                    EntitySpan(
                        start=res.start,
                        end=res.end,
                        text=span_text,
                        category=category,
                    )
                )

        return entities


_default_ner_masker: NERMasker | None = None


def get_ner_masker() -> NERMasker:
    """Returns a module-level singleton instance of NERMasker."""
    global _default_ner_masker
    if _default_ner_masker is None:
        _default_ner_masker = NERMasker()
    return _default_ner_masker

