from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from app.services.privacy.entity_registry import EntityRegistry

# Per-process cache of *derived* session state (never persisted to disk or DB).
#
# The registry of a chat session is rebuilt deterministically from the session's
# persisted messages (``app.services.privacy.session_registry``), so every
# worker computes the same tokens; this cache only avoids re-masking the
# messages that were already processed. Losing an entry (restart, eviction, a
# request served by another worker) costs CPU, never correctness.
#
# Bounded LRU so memory stays flat under sustained load.
MAX_REGISTRIES = 2000


@dataclass(frozen=True)
class CachedSessionState:
    """Registry and masked texts after masking a prefix of a session's messages.

    Attributes:
        message_ids: Ids of the masked messages, in chronological order.
        registry: Registry after masking them. Treat as read-only: callers
            receive a ``clone()``.
        masked: Masked text of each message (same order as ``message_ids``).
    """

    message_ids: tuple[uuid.UUID, ...]
    registry: EntityRegistry
    masked: tuple[str, ...]


_store: OrderedDict[uuid.UUID, CachedSessionState] = OrderedDict()
_lock = threading.Lock()


def get_cached_state(session_id: uuid.UUID) -> CachedSessionState | None:
    """Returns the cached state of a session, or ``None``."""
    with _lock:
        state = _store.get(session_id)
        if state is not None:
            _store.move_to_end(session_id)
        return state


def put_cached_state(session_id: uuid.UUID, state: CachedSessionState) -> None:
    """Stores the state of a session, evicting the least recently used one if full."""
    with _lock:
        _store[session_id] = state
        _store.move_to_end(session_id)
        while len(_store) > MAX_REGISTRIES:
            _store.popitem(last=False)


def clear_registry(session_id: uuid.UUID) -> None:
    """Drops the cached state of a session (the registry is rebuilt on demand)."""
    with _lock:
        _store.pop(session_id, None)


def clear_all() -> None:
    """Drops every cached state (tests, and simulating a fresh worker)."""
    with _lock:
        _store.clear()
