from __future__ import annotations

import uuid

from app.services.privacy.entity_registry import EntityRegistry

# Global in-memory store for session-scoped entity registries (never persisted to disk or DB)
_store: dict[uuid.UUID, EntityRegistry] = {}


def get_registry(session_id: uuid.UUID) -> EntityRegistry:
    """Returns the EntityRegistry for a given session ID, creating it if it doesn't exist."""
    if session_id not in _store:
        _store[session_id] = EntityRegistry()
    return _store[session_id]


def clear_registry(session_id: uuid.UUID) -> None:
    """Clears the EntityRegistry for a given session ID from in-memory store."""
    _store.pop(session_id, None)

