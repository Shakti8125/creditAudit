"""Embedding pin helpers (PR-01, CorpusPlan section 8).

Index vectors and query vectors must come from one model at one size, so embeddings are
pinned: ``NVIDIA_EMBEDDING_MODEL`` at ``EMBEDDING_DIMENSIONS``, never routed to another
provider. This module holds the size check shared by the provider and its tests.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)


class EmbeddingDimensionError(ValueError):
    """The embedding model returned vectors the index cannot hold."""


class EmbeddingNotSupportedError(NotImplementedError):
    """A provider other than the pinned one was asked for embeddings."""


def pin_dimensions(vectors: list[list[float]], dimensions: int) -> list[list[float]]:
    """Return ``vectors`` at exactly ``dimensions`` entries each.

    A vector that already has the right size is returned untouched. A longer one is sliced
    to its first ``dimensions`` entries and L2-renormalised (Matryoshka-style models keep the
    leading entries meaningful). A shorter one cannot be padded without corrupting the index,
    so it raises.

    Args:
        vectors: Raw vectors from the embedding model.
        dimensions: Pinned size; 0 disables the pin.

    Raises:
        EmbeddingDimensionError: A vector is shorter than ``dimensions``.
    """
    if dimensions <= 0:
        return vectors
    pinned: list[list[float]] = []
    sliced = 0
    for vector in vectors:
        if len(vector) == dimensions:
            pinned.append(vector)
        elif len(vector) > dimensions:
            head = vector[:dimensions]
            norm = math.sqrt(sum(x * x for x in head))
            pinned.append([x / norm for x in head] if norm > 0 else head)
            sliced += 1
        else:
            raise EmbeddingDimensionError(
                f"The embedding model returned {len(vector)} dimensions, fewer than "
                f"EMBEDDING_DIMENSIONS={dimensions}. Check that setting against the index size "
                f"and the model."
            )
    if sliced:
        logger.debug("Sliced %d embedding(s) to %d dimensions", sliced, dimensions)
    return pinned
