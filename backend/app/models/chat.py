from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.user import _utc_now


class ChatRoleEnum(str, enum.Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(Base):
    """Persisted conversation history for AI Analyst."""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"), index=True, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    messages: Mapped[list[ChatMessage]] = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at")


class ChatMessage(Base):
    """Individual message in a chat session."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_sessions.id"), index=True, nullable=False)
    role: Mapped[ChatRoleEnum] = mapped_column(SAEnum(ChatRoleEnum), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    sources_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    session: Mapped[ChatSession] = relationship("ChatSession", back_populates="messages")
