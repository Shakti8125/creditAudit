from __future__ import annotations

import logging
import re
from typing import Any

from nemoguardrails.actions import action

logger = logging.getLogger(__name__)

ENGLISH_STOP_WORDS: set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't",
    "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have",
    "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into",
    "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our",
    "ours", "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's",
    "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs",
    "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't",
    "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves"
}

ALLOWED_PLACEHOLDER_PATTERN = re.compile(
    r"^\[(?:BANK|ORG|PERSON|EMAIL|PHONE|GPE|LOC|PRODUCT|SYSTEM|METRIC)_\d+\]$"
)


@action(name="verify_financial_arithmetic_action")
async def verify_financial_arithmetic_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> bool:
    """Verifies model validation metrics:
    - Checks Gini percentages are between 0-100 (or 0-1 decimal)
    - Checks AUC values are between 0-1
    - Checks KS percentages are between 0-100 (or 0-1 decimal)
    - Checks PSI values are non-negative
    - Cross-validates: if Gini is mentioned, AUC should be approximately (Gini/100 + 1) / 2
    """
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    text: str = merged.get("last_bot_message") or merged.get("bot_message") or merged.get("response") or ""
    if not text:
        return True

    number_regex = r"(-?[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|-?[0-9]+(?:\.[0-9]+)?)"
    gini_match = re.search(rf"\bGini(?:\s+coefficient)?(?:\s+is|:|=)?\s*{number_regex}", text, re.IGNORECASE)
    auc_match = re.search(rf"\bAUC(?:\s+ROC)?(?:\s+is|:|=)?\s*{number_regex}", text, re.IGNORECASE)
    ks_match = re.search(rf"\bKS(?:\s+statistic)?(?:\s+is|:|=)?\s*{number_regex}", text, re.IGNORECASE)
    psi_match = re.search(rf"\bPSI(?:\s+is|:|=)?\s*{number_regex}", text, re.IGNORECASE)

    gini_val: float | None = float(gini_match.group(1).replace(",", "")) if gini_match else None
    auc_val: float | None = float(auc_match.group(1).replace(",", "")) if auc_match else None
    ks_val: float | None = float(ks_match.group(1).replace(",", "")) if ks_match else None
    psi_val: float | None = float(psi_match.group(1).replace(",", "")) if psi_match else None

    if gini_val is not None:
        if not (0 <= gini_val <= 100):
            return False
    if auc_val is not None:
        if not (0 <= auc_val <= 1):
            return False
    if ks_val is not None:
        if not (0 <= ks_val <= 100):
            return False
    if psi_val is not None:
        if psi_val < 0:
            return False

    if gini_val is not None and auc_val is not None:
        # Normalize Gini to the 0-1 fraction scale before cross-validating.
        # A Gini reported as a percentage (e.g. 45 for 45%) maps to 0.45.
        gini_norm = gini_val / 100.0 if gini_val > 1.0 else gini_val
        expected_auc = (gini_norm + 1.0) / 2.0
        # Allow a 0.10 margin of tolerance on the 0-1 AUC scale so a Gini
        # reported as a percentage is not falsely flagged against a 0-1 AUC.
        if abs(expected_auc - auc_val) > 0.10:
            return False

    return True


@action(name="check_hallucination_action")
async def check_hallucination_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> float:
    """Grounding overlap check:
    - Decimal-safe tokenization preserving comma-formatted financial numbers
    - Filters out English stop words from token overlap calculation
    - Returns hallucination probability 0.0 to 1.0 (where 0.0 means perfect overlap, 1.0 means complete hallucination)
    """
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    bot_message: str = (
        merged.get("last_bot_message")
        or merged.get("bot_message")
        or merged.get("response")
        or ""
    )
    
    retrieved_raw = merged.get("retrieved_contexts", [])
    if isinstance(retrieved_raw, str):
        retrieved_list = [retrieved_raw]
    elif isinstance(retrieved_raw, list):
        retrieved_list = [str(r) for r in retrieved_raw if r]
    else:
        retrieved_list = []

    context_str = merged.get("context", "")
    if context_str and isinstance(context_str, str):
        retrieved_list.append(context_str)

    if not bot_message or not retrieved_list:
        return 0.0

    context_text = " ".join(retrieved_list).lower()

    # Match words and comma-separated/decimal numbers as single tokens
    tokens = re.findall(
        r"\b(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|[a-zA-Z_]+)\b",
        bot_message.lower()
    )

    meaningful_tokens = [t for t in tokens if t not in ENGLISH_STOP_WORDS]
    if not meaningful_tokens:
        return 0.0

    unique_tokens = set(meaningful_tokens)
    overlap_count = sum(1 for token in unique_tokens if token in context_text)
    overlap_ratio = overlap_count / len(unique_tokens)

    hallucination_prob = max(0.0, min(1.0, 1.0 - overlap_ratio))
    return round(hallucination_prob, 4)


@action(name="check_placeholder_integrity_action")
async def check_placeholder_integrity_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> bool:
    """Ensure no broken or malformed entity masking placeholders exist in output.
    Allowed entity token format: [CATEGORY_ID], e.g., [BANK_1], [ORG_2], [PERSON_1].
    Any broken bracket pattern (e.g. [BANK], [[BANK_1]], [ORG_]) returns False.
    """
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    text: str = (
        merged.get("last_bot_message")
        or merged.get("bot_message")
        or merged.get("response")
        or ""
    )
    if not text:
        return True

    # Check for bracket balance and double brackets
    if text.count("[") != text.count("]"):
        return False
    if "[[" in text or "]]" in text:
        return False

    # Extract all bracketed items
    bracketed_items = re.findall(r"\[([^\]]*)\]", text)
    known_categories = {
        "BANK", "ORG", "PERSON", "EMAIL", "PHONE",
        "GPE", "LOC", "PRODUCT", "SYSTEM", "METRIC"
    }

    for item in bracketed_items:
        clean_item = item.strip()
        bracket_token = f"[{clean_item}]"

        # Check if it targets an entity category or uppercase identifier
        parts = clean_item.split("_")
        prefix = parts[0].upper() if parts else ""

        if prefix in known_categories or (clean_item.isupper() and "_" in clean_item):
            if not ALLOWED_PLACEHOLDER_PATTERN.match(bracket_token):
                return False
        elif prefix in known_categories:
            # e.g., [BANK] without underscore or ID
            return False

        # Malformed empty or punctuation-only brackets
        if clean_item == "" or clean_item == "_":
            return False

    return True


@action(name="check_jailbreak_action")
async def check_jailbreak_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> bool:
    """Checks for prompt injection and jailbreak patterns in user messages."""
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    user_message: str = (
        merged.get("last_user_message")
        or merged.get("user_message")
        or merged.get("prompt")
        or ""
    ).lower()

    if not user_message:
        return True

    jailbreak_keywords = [
        "ignore previous",
        "disregard all",
        "system prompt",
        "you are an unrestricted",
        "jailbreak",
        "bypass safety",
        "forget your instructions",
        "act as an unfiltered",
    ]
    for keyword in jailbreak_keywords:
        if keyword in user_message:
            return False

    return True


@action(name="check_off_topic_action")
async def check_off_topic_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> bool:
    """Checks if a user query falls outside the credit risk model validation domain boundary.
    Returns True if off-topic, False if on-topic.
    """
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    user_message: str = (
        merged.get("last_user_message")
        or merged.get("user_message")
        or merged.get("prompt")
        or ""
    ).strip().lower()

    if not user_message:
        return False

    off_topic_indicators = [
        "python script",
        "what stocks",
        "who is the president",
        "cook dinner",
        "poem about",
        "bake a cake",
        "movie recommendation",
        "weather in",
    ]

    for pattern in off_topic_indicators:
        if pattern in user_message:
            return True

    return False


@action(name="check_prompt_injection_action")
async def check_prompt_injection_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> bool:
    """Checks for prompt injection patterns in user messages.

    Returns True when the message is safe, False when an injection pattern
    is detected (mirroring the jailbreak check's pass/fail convention).
    """
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    user_message: str = (
        merged.get("last_user_message")
        or merged.get("user_message")
        or merged.get("prompt")
        or ""
    ).lower()

    if not user_message:
        return True

    injection_indicators = [
        "reveal your instructions",
        "show your system prompt",
        "developer mode",
        "ignore all previous",
        "disregard prior instructions",
        "pretend you are",
        "act as an unfiltered",
    ]
    for pattern in injection_indicators:
        if pattern in user_message:
            return False

    return True


@action(name="mask_pii_entities_action")
async def mask_pii_entities_action(
    context: dict[str, Any] | None = None,
    **kwargs: Any
) -> str:
    """Masks obvious PII patterns (emails and phone numbers) in the user message.

    Uses the same bracketed entity placeholders as the downstream masking
    pipeline so masked values remain recognizable to the output integrity check.
    Returns the masked message, or the original message when no PII is present.
    """
    merged: dict[str, Any] = {**(context or {}), **kwargs}
    user_message: str = (
        merged.get("last_user_message")
        or merged.get("user_message")
        or merged.get("prompt")
        or ""
    )

    if not user_message:
        return ""

    masked = re.sub(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "[EMAIL_0]",
        user_message,
    )
    masked = re.sub(
        r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "[PHONE_0]",
        masked,
    )

    return masked


