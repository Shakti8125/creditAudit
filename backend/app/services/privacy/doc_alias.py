"""Document aliases (``DOC-n``) for everything that goes into an LLM prompt.

An uploaded document is identified inside a prompt by an alias such as ``DOC-1``,
never by its filename. Filenames are tenant data: they can name a bank or a
model, the masker registers them as entities once an answer repeats them, and a
registered entity that still appears raw in the next prompt is a hard egress
block (QA-004). The alias is a stable, content-free label for one request; the
UI maps it back to the filename for display (the UI is not a provider).

``source`` strings of document chunks are ``doc-<document id>`` everywhere
(Pinecone metadata, BM25, citations), the same identity in every retriever.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.retrieval import Citation

# ``DOC-1`` ... ``DOC-999``, any case. Not preceded or followed by a word
# character or a hyphen, so the ``doc-<uuid>`` source ids do not match.
DOC_ALIAS_PATTERN = re.compile(r"(?<![\w-])DOC-\d{1,3}(?![\w-])", re.IGNORECASE)

DOC_SOURCE_PREFIX = "doc-"


def doc_source(document_id: uuid.UUID | str) -> str:
    """Return the content-free citation ``source`` of a document's chunks.

    Args:
        document_id: Document identifier.

    Returns:
        ``doc-<document id>``.
    """
    return f"{DOC_SOURCE_PREFIX}{document_id}"


def assign_doc_aliases(
    citations: Iterable[Citation],
    primary_document_id: uuid.UUID | str | None = None,
) -> dict[str, str]:
    """Assign ``DOC-n`` aliases to the documents cited in one request.

    The primary document (the one the chat is scoped to) is always ``DOC-1``;
    any other cited document follows in order of first appearance, so the
    numbering is deterministic for the same retrieval result.

    Args:
        citations: Retrieved citations in rank order.
        primary_document_id: Document the request is scoped to, if any.

    Returns:
        Mapping ``document_id -> alias``. Citations without a ``document_id``
        (public regulatory text) get no alias.
    """
    order: list[str] = []
    if primary_document_id is not None:
        order.append(str(primary_document_id))
    for citation in citations:
        if citation.document_id and citation.document_id not in order:
            order.append(citation.document_id)
    return {document_id: f"DOC-{index}" for index, document_id in enumerate(order, start=1)}


def apply_doc_aliases(citations: Iterable[Citation], aliases: dict[str, str]) -> list[Citation]:
    """Return copies of ``citations`` with their ``alias`` set from ``aliases``.

    Args:
        citations: Retrieved citations.
        aliases: Mapping from :func:`assign_doc_aliases`.

    Returns:
        New citations; those of a document carry its alias, public ones none.
    """
    return [
        c.model_copy(update={"alias": aliases.get(c.document_id) if c.document_id else None})
        for c in citations
    ]


def expand_aliases(text: str, filenames_by_alias: dict[str, str]) -> str:
    """Replace aliases in ``text`` with display names (UI-side use only).

    Never call this on text that is about to be sent to a provider.

    Args:
        text: Text containing ``DOC-n`` aliases.
        filenames_by_alias: Mapping ``DOC-n -> display name`` (case-insensitive key).

    Returns:
        ``text`` with every known alias replaced.
    """
    if not filenames_by_alias:
        return text
    upper = {alias.upper(): name for alias, name in filenames_by_alias.items()}
    return DOC_ALIAS_PATTERN.sub(lambda m: upper.get(m.group(0).upper(), m.group(0)), text)
