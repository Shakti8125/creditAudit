from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Tuple

# Token pattern: preserves comma-formatted financial numbers (e.g. 1,250,000 or 98.5) and alphanumeric words/tokens
_TOKEN_PATTERN = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+(?:\.\d+)?\b|[a-zA-Z0-9_-]+")


class BM25Okapi:
    """Zero-dependency BM25Okapi implementation for lexical search."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        """Initialize BM25Okapi parameters.

        Args:
            k1: Term frequency saturation parameter.
            b: Document length normalization parameter.
        """
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avgdl = 0.0
        self.doc_freqs: List[Counter[str]] = []
        self.idf: dict[str, float] = {}
        self.doc_len: List[int] = []
        self.corpus: List[str] = []

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text preserving words and comma-formatted financial numbers.

        Args:
            text: Input string.

        Returns:
            List of lowercase string tokens.
        """
        if not text:
            return []
        return _TOKEN_PATTERN.findall(text.lower())

    def fit(self, corpus: List[str]) -> None:
        """Fit BM25 index on a new corpus.

        Resets internal state to prevent contamination across multiple fit calls.

        Args:
            corpus: List of raw document strings.
        """
        # RET-08: Reset state at start of fit
        self.corpus = list(corpus)
        self.corpus_size = len(corpus)
        self.doc_freqs = []
        self.doc_len = []
        self.idf = {}
        self.avgdl = 0.0

        if self.corpus_size == 0:
            return

        nd: dict[str, int] = {}
        num_doc = 0
        total_len = 0

        for document in corpus:
            tokens = self._tokenize(document)
            doc_len = len(tokens)
            frequencies = Counter(tokens)
            self.doc_freqs.append(frequencies)

            for word in frequencies:
                nd[word] = nd.get(word, 0) + 1

            self.doc_len.append(doc_len)
            total_len += doc_len
            num_doc += 1

        self.avgdl = total_len / num_doc if num_doc > 0 else 0.0

        # Calculate IDF: ln((N - n_q + 0.5) / (n_q + 0.5) + 1.0)
        for word, freq in nd.items():
            idf = math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)
            self.idf[word] = idf

    def score(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Score query against indexed corpus.

        Args:
            query: Search query string.
            top_k: Max top results to return.

        Returns:
            List of (doc_index, score) tuples sorted by score descending.
        """
        if self.corpus_size == 0:
            return []

        q_tokens = self._tokenize(query)
        if not q_tokens:
            return []

        scores: List[Tuple[int, float]] = []
        for index in range(self.corpus_size):
            score = 0.0
            frequencies = self.doc_freqs[index]
            d_len = self.doc_len[index]

            # RET-10: Guard against ZeroDivisionError when avgdl == 0
            len_norm = (d_len / self.avgdl) if self.avgdl > 0 else 1.0

            for token in q_tokens:
                if token not in frequencies:
                    continue

                f = frequencies[token]
                idf = self.idf.get(token, 0.0)

                numerator = f * (self.k1 + 1)
                denominator = f + self.k1 * (1 - self.b + self.b * len_norm)
                if denominator > 0:
                    score += idf * (numerator / denominator)

            scores.append((index, score))

        # Sort and return top_k
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

