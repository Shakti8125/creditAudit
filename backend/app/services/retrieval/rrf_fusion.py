from __future__ import annotations

import hashlib
from typing import Dict, List

from app.schemas.retrieval import RetrievalCandidate


def _hash_text(text: str) -> str:
    """Compute sha256 hash of text for deduplication."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rrf_fuse(
    ranked_lists: List[List[RetrievalCandidate]],
    k: int = 60,
) -> List[RetrievalCandidate]:
    """Implements Reciprocal Rank Fusion algorithm to fuse multiple ranked lists.

    Normalizes the combined reciprocal rank scores to the [0, 1] range based on
    the theoretical maximum score achievable across all input ranked lists.

    Args:
        ranked_lists: List of ranked candidate lists from different retrieval systems.
        k: Smoothing constant (default 60).

    Returns:
        Deduplicated list of RetrievalCandidate objects with normalized scores in [0, 1],
        sorted by fused score descending.
    """
    valid_lists = [lst for lst in ranked_lists if lst]
    if not valid_lists:
        return []

    rrf_scores: Dict[str, float] = {}
    candidates_map: Dict[str, RetrievalCandidate] = {}

    for ranked_list in valid_lists:
        for rank, candidate in enumerate(ranked_list, start=1):
            text_hash = _hash_text(candidate.chunk_text)

            # Store the first candidate encountered for this text to preserve metadata
            if text_hash not in candidates_map:
                candidates_map[text_hash] = candidate
                rrf_scores[text_hash] = 0.0

            # Add RRF score: 1 / (k + rank)
            rrf_scores[text_hash] += 1.0 / (k + rank)

    # RET-14: Theoretical max score when a document is rank 1 across all valid ranked lists
    max_possible_score = sum(1.0 / (k + 1) for _ in valid_lists)
    if max_possible_score <= 0.0:
        max_possible_score = 1.0

    # Build cloned candidate objects with normalized score in [0, 1]
    fused_candidates: List[RetrievalCandidate] = []
    for text_hash, raw_score in rrf_scores.items():
        base_cand = candidates_map[text_hash]
        normalized_score = min(1.0, max(0.0, raw_score / max_possible_score))

        fused_candidates.append(
            base_cand.model_copy(
                update={
                    "score": normalized_score,
                    "retrieval_method": "hybrid_rrf",
                }
            )
        )

    # Sort by normalized RRF score descending
    fused_candidates.sort(key=lambda x: x.score, reverse=True)
    return fused_candidates

