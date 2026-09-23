"""Pure metric functions for RAG telemetry and offline evaluation.

No I/O and no application imports: everything here is deterministic maths over
plain Python values, so it is cheap to unit test and safe to reuse anywhere.

Relevance judging, IR metrics (Hit/Precision/Recall/MRR/nDCG @k), token-overlap
proxies (groundedness, question coverage, SQuAD token F1), percentiles and
retrieval score normalisation are defined here and are the source of truth for
the evaluation tests.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

# Copied (not imported) from guardrails/actions.ENGLISH_STOP_WORDS so this module
# stays dependency-free.
STOPWORDS: frozenset[str] = frozenset({
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
    "yourselves",
})

# Comma-grouped numbers stay one token (AGENTS.md rule 10: never split 1,250,000).
_TOKEN_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|[a-z][a-z0-9_\-]*")
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―"), "-")
_WHITESPACE_RE = re.compile(r"\s+")
_CITATION_RE = re.compile(r"\[Source:\s*[^\]]+\]", re.IGNORECASE)


# --------------------------------------------------------------------------- text


def normalize_text(text: str) -> str:
    """Normalise text for matching: unicode dashes to '-', lowercase, collapsed whitespace.

    Args:
        text: Arbitrary text.

    Returns:
        The normalised string ("" for empty input).
    """
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.translate(_DASHES).lower()).strip()


def text_fingerprint(text: str) -> str:
    """Return the sha256 hex digest of ``normalize_text(text)``.

    Args:
        text: Chunk text.

    Returns:
        64-character hex digest.
    """
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def section_matches(expected: str, actual: str) -> bool:
    """Whether a retrieved section label matches an expected section label.

    Matches on equality, or when ``actual`` starts with ``expected`` and the next
    character is not alphanumeric (so "Section 1" does not match "Section 10 - ...").

    Args:
        expected: Section label from the golden case.
        actual: Section label of the retrieved item.

    Returns:
        True on a match.
    """
    e = normalize_text(expected)
    a = normalize_text(actual)
    if not e:
        return False
    if a == e:
        return True
    return a.startswith(e) and not a[len(e)].isalnum()


def keyword_hits(text: str, keywords: Sequence[str]) -> int:
    """Count keywords (normalised) that occur as substrings of the normalised text.

    Args:
        text: Retrieved text.
        keywords: Keywords to look for.

    Returns:
        Number of keywords found.
    """
    haystack = normalize_text(text)
    return sum(1 for kw in keywords if (needle := normalize_text(kw)) and needle in haystack)


def required_keyword_hits(keywords: Sequence[str], min_hits: int | None) -> int:
    """Minimum keyword hits for a keyword target to count as matched.

    Args:
        keywords: Target keywords.
        min_hits: Explicit threshold, or None for the default of ceil(60%).

    Returns:
        ``min(len(keywords), min_hits)`` if set, else ``max(1, ceil(0.6 * len(keywords)))``.
    """
    if min_hits:
        return min(len(keywords), min_hits)
    return max(1, math.ceil(0.6 * len(keywords)))


# --------------------------------------------------------------------------- relevance


@dataclass(frozen=True)
class RelevanceTarget:
    """One expected piece of evidence for a golden case.

    Attributes:
        source: Expected source label (exact after normalisation), if any.
        section: Expected section label (prefix-safe match), if any.
        keywords: Keywords the retrieved text should contain.
        min_keyword_hits: Explicit keyword threshold (default ceil(60%)).
        text_hash: ``text_fingerprint`` of a specific chunk (chunk_index targets).
    """

    source: str | None = None
    section: str | None = None
    keywords: tuple[str, ...] = ()
    min_keyword_hits: int | None = None
    text_hash: str | None = None


@dataclass(frozen=True)
class RetrievedItem:
    """A retrieved passage as seen by the relevance judge."""

    source: str
    section: str
    text: str


def target_matches(target: RelevanceTarget, item: RetrievedItem) -> bool:
    """Whether a retrieved item satisfies a relevance target.

    Any of: (1) text fingerprint equality, (2) source/section reference match,
    (3) enough keyword hits.

    Args:
        target: The relevance target.
        item: The retrieved item.

    Returns:
        True on a match.
    """
    if target.text_hash and text_fingerprint(item.text) == target.text_hash:
        return True
    if target.source or target.section:
        source_ok = target.source is None or normalize_text(target.source) == normalize_text(item.source)
        section_ok = target.section is None or section_matches(target.section, item.section)
        if source_ok and section_ok:
            return True
    if target.keywords:
        needed = required_keyword_hits(target.keywords, target.min_keyword_hits)
        if keyword_hits(item.text, target.keywords) >= needed:
            return True
    return False


def judge_relevance(
    items: Sequence[RetrievedItem],
    targets: Sequence[RelevanceTarget],
) -> tuple[list[int], list[list[int]]]:
    """Binary relevance per rank plus the target indices each item matches.

    Args:
        items: Retrieved items in rank order.
        targets: Relevance targets of the case.

    Returns:
        ``(relevances, matched)`` where ``relevances[i]`` is 1 if item i matches at
        least one target and ``matched[i]`` lists the sorted target indices it matches.
    """
    relevances: list[int] = []
    matched: list[list[int]] = []
    for item in items:
        hits = [t_idx for t_idx, target in enumerate(targets) if target_matches(target, item)]
        matched.append(sorted(hits))
        relevances.append(1 if hits else 0)
    return relevances, matched


# --------------------------------------------------------------------------- IR metrics


def _check_k(k: int) -> None:
    """Raise ValueError when k < 1."""
    if k < 1:
        raise ValueError(f"k must be >= 1 (got {k})")


def hit_at_k(relevances: Sequence[int], k: int) -> float:
    """1.0 if any of the top-k items is relevant, else 0.0."""
    _check_k(k)
    return 1.0 if any(relevances[:k]) else 0.0


def precision_at_k(relevances: Sequence[int], k: int) -> float:
    """Relevant items in the top-k divided by k (denominator is k even if fewer items)."""
    _check_k(k)
    return sum(1 for r in relevances[:k] if r) / k


def recall_at_k(matched_per_rank: Sequence[Sequence[int]], n_targets: int, k: int) -> float:
    """Distinct targets covered by the top-k items divided by the number of targets."""
    _check_k(k)
    if n_targets <= 0:
        return 0.0
    covered: set[int] = set()
    for matched in matched_per_rank[:k]:
        covered.update(matched)
    return len(covered) / n_targets


def first_relevant_rank(relevances: Sequence[int], k: int) -> int | None:
    """1-based rank of the first relevant item within the top-k, or None."""
    _check_k(k)
    for idx, rel in enumerate(relevances[:k]):
        if rel:
            return idx + 1
    return None


def reciprocal_rank_at_k(relevances: Sequence[int], k: int) -> float:
    """1 / first relevant rank within the top-k, or 0.0."""
    rank = first_relevant_rank(relevances, k)
    return 1.0 / rank if rank else 0.0


def dcg_at_k(relevances: Sequence[int], k: int) -> float:
    """Discounted cumulative gain with binary gains: sum(rel_i / log2(i + 1)), i = 1..k."""
    _check_k(k)
    return sum((1.0 if rel else 0.0) / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def ndcg_at_k(matched_per_rank: Sequence[Sequence[int]], k: int, n_targets: int) -> float:
    """Target-coverage nDCG@k.

    A rank earns gain for each target it covers that no higher-ranked item already
    covered, so several chunks of the same relevant section are not penalised (a
    duplicate simply adds nothing). The ideal list covers one new target per rank for
    ``min(k, n_targets)`` ranks; the result is clamped to 1.0.

    Args:
        matched_per_rank: Target indices matched per rank (see ``judge_relevance``).
        k: Cut-off.
        n_targets: Number of relevance targets of the case.

    Returns:
        nDCG in [0, 1]; 0.0 when the case has no targets.
    """
    _check_k(k)
    ideal_len = min(k, n_targets)
    if ideal_len <= 0:
        return 0.0
    covered: set[int] = set()
    dcg = 0.0
    for i, matched in enumerate(matched_per_rank[:k]):
        new = set(matched) - covered
        if new:
            dcg += len(new) / math.log2(i + 2)
            covered |= new
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_len))
    return min(1.0, dcg / idcg)


@dataclass(frozen=True)
class CaseRetrievalScores:
    """Retrieval scores of one golden case at a fixed k."""

    hit: bool
    first_relevant_rank: int | None
    recall: float
    precision: float
    reciprocal_rank: float
    ndcg: float
    targets_matched: int


def score_case(
    relevances: Sequence[int],
    matched_per_rank: Sequence[Sequence[int]],
    n_targets: int,
    k: int,
) -> CaseRetrievalScores:
    """Compute every retrieval metric for one case at k.

    Args:
        relevances: Binary relevance per rank.
        matched_per_rank: Target indices matched per rank.
        n_targets: Number of relevance targets of the case.
        k: Cut-off.

    Returns:
        CaseRetrievalScores.
    """
    _check_k(k)
    covered: set[int] = set()
    for matched in matched_per_rank[:k]:
        covered.update(matched)
    return CaseRetrievalScores(
        hit=bool(hit_at_k(relevances, k)),
        first_relevant_rank=first_relevant_rank(relevances, k),
        recall=recall_at_k(matched_per_rank, n_targets, k),
        precision=precision_at_k(relevances, k),
        reciprocal_rank=reciprocal_rank_at_k(relevances, k),
        ndcg=ndcg_at_k(matched_per_rank, k, n_targets),
        targets_matched=len(covered),
    )


def metric_curves(
    cases: Sequence[tuple[Sequence[int], Sequence[Sequence[int]], int]],
    k_max: int,
) -> dict[str, list[float]]:
    """Mean Hit/Recall/Precision/nDCG at every k in 1..k_max.

    Args:
        cases: ``(relevances, matched_per_rank, n_targets)`` per case.
        k_max: Largest cut-off.

    Returns:
        ``{"k": [...], "hit": [...], "recall": [...], "precision": [...], "ndcg": [...]}``;
        every list is empty when there are no cases.
    """
    curves: dict[str, list[float]] = {"k": [], "hit": [], "recall": [], "precision": [], "ndcg": []}
    if not cases or k_max < 1:
        return curves
    n = len(cases)
    for k in range(1, k_max + 1):
        curves["k"].append(k)
        curves["hit"].append(sum(hit_at_k(r, k) for r, _, _ in cases) / n)
        curves["recall"].append(sum(recall_at_k(m, t, k) for _, m, t in cases) / n)
        curves["precision"].append(sum(precision_at_k(r, k) for r, _, _ in cases) / n)
        curves["ndcg"].append(sum(ndcg_at_k(m, k, t) for _, m, t in cases) / n)
    return curves


# --------------------------------------------------------------------------- answer proxies


def tokenize(text: str) -> list[str]:
    """Tokenise normalised text, keeping comma-grouped numbers as single tokens."""
    return _TOKEN_RE.findall(normalize_text(text))


def content_tokens(text: str) -> list[str]:
    """Tokens minus stopwords and single-character tokens."""
    return [t for t in tokenize(text) if len(t) > 1 and t not in STOPWORDS]


def groundedness(answer: str, contexts: Sequence[str]) -> float | None:
    """Share of the answer's distinct content tokens present in the retrieved context.

    Args:
        answer: Generated answer.
        contexts: Retrieved context strings.

    Returns:
        ``|A ∩ C| / |A|`` or None when the answer has no content tokens.
    """
    answer_tokens = set(content_tokens(answer))
    if not answer_tokens:
        return None
    context_tokens = set(content_tokens(" ".join(contexts)))
    return len(answer_tokens & context_tokens) / len(answer_tokens)


def question_coverage(question: str, answer: str) -> float | None:
    """Share of the question's distinct content tokens echoed by the answer (None if no tokens)."""
    question_tokens = set(content_tokens(question))
    if not question_tokens:
        return None
    return len(question_tokens & set(content_tokens(answer))) / len(question_tokens)


def token_f1(prediction: str, reference: str) -> float | None:
    """SQuAD-style token F1 over content-token multisets.

    Args:
        prediction: Candidate answer.
        reference: Reference answer.

    Returns:
        F1 in [0, 1]; None when the reference has no content tokens.
    """
    ref_tokens = content_tokens(reference)
    if not ref_tokens:
        return None
    pred_tokens = content_tokens(prediction)
    common = Counter(pred_tokens) & Counter(ref_tokens)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred_tokens)
    recall = overlap / len(ref_tokens)
    return 2 * precision * recall / (precision + recall)


def count_inline_citations(answer: str) -> int:
    """Number of inline ``[Source: ...]`` citations in an answer."""
    if not answer:
        return 0
    return len(_CITATION_RE.findall(answer))


def estimate_tokens(text: str) -> int:
    """Rough token estimate (characters / 4, rounded up)."""
    if not text:
        return 0
    return math.ceil(len(text) / 4)


# --------------------------------------------------------------------------- statistics


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolation percentile (numpy default, Hyndman-Fan type 7).

    Args:
        values: Sample values.
        q: Percentile in [0, 100].

    Returns:
        The percentile, or None for an empty sample.
    """
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    q = min(100.0, max(0.0, float(q)))
    h = (len(ordered) - 1) * q / 100.0
    lower = math.floor(h)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (h - lower) * (ordered[upper] - ordered[lower])


def mean_or_none(values: Iterable[float | None]) -> float | None:
    """Arithmetic mean ignoring None values (None when nothing remains)."""
    present = [float(v) for v in values if v is not None]
    if not present:
        return None
    return sum(present) / len(present)


def safe_rate(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator`` or None when the denominator is 0."""
    if denominator == 0:
        return None
    return numerator / denominator


# --------------------------------------------------------------------------- scores


def classify_score_kind(retrieval_method: str | None, rerank_provider: str | None) -> str | None:
    """Map a citation's retrieval method (and rerank provider) to a ScoreKind.

    Args:
        retrieval_method: ``Citation.retrieval_method`` of the top citation.
        rerank_provider: Provider that served the rerank call, if any.

    Returns:
        One of ``rerank_nvidia``, ``rerank_gemini``, ``rerank``, ``rrf``, ``dense``,
        ``bm25``, or None.
    """
    if not retrieval_method:
        return None
    if retrieval_method.endswith("_reranked"):
        if rerank_provider == "nvidia":
            return "rerank_nvidia"
        if rerank_provider == "gemini":
            return "rerank_gemini"
        return "rerank"
    if retrieval_method == "hybrid_rrf":
        return "rrf"
    if retrieval_method == "dense":
        return "dense"
    if retrieval_method == "bm25":
        return "bm25"
    return None


def _clamp_unit(value: float) -> float:
    """Clamp to [0, 1]."""
    return min(1.0, max(0.0, value))


def _sigmoid(x: float) -> float:
    """Numerically stable logistic function."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def normalize_score(kind: str | None, score: float | None) -> float | None:
    """Map a raw top score onto [0, 1] so different scorers can be compared.

    NVIDIA rerank returns logits (sigmoid), Gemini rerank 0-10 (divide by 10),
    RRF and dense cosine are already ~0-1 (clamped). BM25 is unbounded and unknown
    kinds are not normalised.

    Args:
        kind: ScoreKind from ``classify_score_kind``.
        score: Raw score.

    Returns:
        Normalised score or None.
    """
    if score is None or kind is None:
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    if kind == "rerank_nvidia":
        return _sigmoid(value)
    if kind == "rerank_gemini":
        return _clamp_unit(value / 10.0)
    if kind in ("rrf", "dense"):
        return _clamp_unit(value)
    return None
