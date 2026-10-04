"""Deterministic, derived entity registry of a chat session (QA-004, QA-011).

The registry is **never persisted**. It is rebuilt on demand by masking the
session's already-persisted messages in chronological order, then (for a new
turn) the new question. Masking is a deterministic function of the text and of
the registry so far, and the message order is canonical (``created_at``, then
``id``), so every worker, and every request, derives the same tokens for the
same conversation. That is what keeps ``[ORG_1]`` the same entity from turn to
turn and lets ``GET /privacy/redactions`` return the same map on every worker.

A per-process cache (:mod:`app.services.privacy.registry_store`) skips the
messages that were already masked. It is an optimisation only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession
from app.services.privacy.entity_registry import EntityRegistry
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.registry_store import (
    CachedSessionState,
    get_cached_state,
    put_cached_state,
)

# Longest conversation the rebuild supports (user + assistant messages). It bounds the
# CPU of a rebuild and keeps the prompt history small. ``POST /query`` refuses further
# turns in a session at this size; the UI tells the user to start a new conversation.
MAX_SESSION_MESSAGES = 50

SESSION_TOO_LONG_DETAIL = (
    f"This conversation has reached its limit of {MAX_SESSION_MESSAGES} messages. "
    "Start a new conversation to continue."
)


class SessionMessage(NamedTuple):
    """The part of a persisted chat message the registry needs."""

    id: uuid.UUID
    role: str
    content: str


@dataclass
class HistoryTurn:
    """One persisted message as it may be shown to a provider (masked)."""

    role: str
    masked_text: str


@dataclass
class SessionPrivacyState:
    """Derived privacy state of a chat session.

    Attributes:
        registry: Registry after masking every persisted message. Independent of
            the cache: masking more text with it (the new question) is safe.
        history: Masked persisted messages in chronological order.
    """

    registry: EntityRegistry
    history: list[HistoryTurn]

    def history_context(self) -> str:
        """Render the history for a prompt, one ``Role: text`` line per message.

        A message is masked before the later ones are seen, so an entity that a later
        message (or the new question) revealed can still be raw in an earlier message.
        Each line is therefore passed through the *current* registry once more; call this
        after masking the new question. It only ever replaces raw entity strings.

        Returns:
            The masked conversation history; empty for a new session.
        """
        return "\n".join(
            f"{turn.role.capitalize()}: {self.registry.apply_to_text(turn.masked_text)}"
            for turn in self.history
        )


async def load_session_messages(
    db: AsyncSession,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[SessionMessage]:
    """Load a session's persisted messages in the canonical order.

    Args:
        db: Active database session.
        session_id: Chat session (the caller has already checked ownership).
        tenant_id: Tenant from the JWT; the query is tenant-scoped as well.

    Returns:
        Messages ordered by ``created_at`` then ``id``.
    """
    result = await db.execute(
        select(ChatMessage.id, ChatMessage.role, ChatMessage.content)
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(ChatMessage.session_id == session_id, ChatSession.tenant_id == tenant_id)
        .order_by(ChatMessage.created_at, ChatMessage.id)
    )
    return [SessionMessage(mid, role.value, content) for mid, role, content in result.all()]


def build_session_state(
    session_id: uuid.UUID,
    messages: list[SessionMessage],
    pipeline: MaskingPipeline,
) -> SessionPrivacyState:
    """Rebuild the registry and masked history of a session (CPU-bound: run in a thread).

    Masks ``messages`` in order with one growing registry. When the cache holds
    the state for a prefix of ``messages`` only the rest is masked; the result is
    identical either way.

    Args:
        session_id: Chat session id (cache key).
        messages: Persisted messages in the canonical order, at most
            ``MAX_SESSION_MESSAGES``.
        pipeline: Masking pipeline.

    Returns:
        The derived state. ``registry`` is a private copy.
    """
    ids = tuple(m.id for m in messages)
    cached = get_cached_state(session_id)
    if cached is not None and ids[: len(cached.message_ids)] == cached.message_ids:
        registry = cached.registry.clone()
        masked = list(cached.masked)
    else:
        registry = EntityRegistry()
        masked = []

    for message in messages[len(masked):]:
        text, _ = pipeline.mask_document(message.content, registry=registry)
        masked.append(text)

    if messages:
        put_cached_state(
            session_id,
            CachedSessionState(message_ids=ids, registry=registry.clone(), masked=tuple(masked)),
        )
    return SessionPrivacyState(
        registry=registry,
        history=[HistoryTurn(m.role, text) for m, text in zip(messages, masked)],
    )
