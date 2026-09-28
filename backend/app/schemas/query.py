from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Any, Optional, List
from uuid import UUID
from app.models.chat import ChatRoleEnum
from app.schemas.retrieval import Citation

class QueryRequest(BaseModel):
    """Request body for the conversational ``POST /query`` endpoint.

    Attributes:
        document_id: Explicit document to ground the answer in.
        question: The user's question.
        session_id: Existing chat session (owned by the caller) to continue.
        model_version_id: Model version to scope the chat to. When no
            ``document_id`` is given, the latest READY document of this
            version is used for retrieval.
    """

    model_config = ConfigDict(from_attributes=True)
    document_id: Optional[UUID] = None
    question: str
    session_id: Optional[UUID] = None
    model_version_id: Optional[UUID] = None

class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    answer: str
    citations: List[Citation]


class ChatSessionSummary(BaseModel):
    """One of the caller's chat sessions, as listed by ``GET /query/sessions``.

    Attributes:
        id: Chat session id.
        model_version_id: Model version the session is scoped to, if any.
        created_at: Session creation time (UTC).
        message_count: Number of persisted user + assistant messages.
        last_message_preview: Truncated content of the most recent message.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_version_id: Optional[UUID] = None
    created_at: datetime
    message_count: int = 0
    last_message_preview: Optional[str] = None


class ChatMessageResponse(BaseModel):
    """A persisted chat message, as returned by ``GET /query/sessions/{id}/messages``.

    Attributes:
        id: Message id.
        role: ``"user"`` or ``"assistant"``.
        content: Message text as stored (the user's original question or the
            streamed assistant answer).
        sources_json: Citations attached to an assistant answer
            (``{source, section, text, score, retrieval_method}`` items), else ``None``.
        created_at: Message creation time (UTC).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: ChatRoleEnum
    content: str
    sources_json: Optional[List[dict[str, Any]]] = None
    created_at: datetime
