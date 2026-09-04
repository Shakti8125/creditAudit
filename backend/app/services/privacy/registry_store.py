from __future__ import annotations

import uuid
from collections import OrderedDict

from app.services.privacy.entity_registry import EntityRegistry

# Global in-memory store for session-scoped entity registries (never persisted to disk or DB)
# Uses bounded LRU structure to avoid unbounded memory growth under sustained load
MAX_REGISTRIES = 2000
_store: OrderedDict[uuid.UUID, EntityRegistry] = OrderedDict()


def get_registry(session_id: uuid.UUID) -> EntityRegistry:
    """Returns the EntityRegistry for a given session ID, creating it if it doesn't exist."""
    if session_id in _store:
        _store.move_to_end(session_id)
        return _store[session_id]

    if len(_store) >= MAX_REGISTRIES:
        _store.popitem(last=False)

    registry = EntityRegistry()
    _store[session_id] = registry
    return registry


def clear_registry(session_id: uuid.UUID) -> None:
    """Clears the EntityRegistry for a given session ID from in-memory store."""
    _store.pop(session_id, None)

