from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class DocumentStatus(str, enum.Enum):
    """Document processing status enumeration."""

    PROCESSING = "PROCESSING"
    READY = "READY"
    ERROR = "ERROR"


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class Document(Base):
    """Document ORM model."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"), index=True, nullable=True)

    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_type: Mapped[str] = mapped_column(String, nullable=False)
    upload_time: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
    raw_markdown: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), default=DocumentStatus.PROCESSING, nullable=False
    )
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=True, default=dict)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def chunk_count(self) -> int:
        """Return the number of chunks associated with this document."""
        return len(self.chunks) if self.chunks else 0


class DocumentChunk(Base):
    """Document chunk ORM model."""

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    masked_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_id: Mapped[str | None] = mapped_column(String, nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")
