from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.user import _utc_now


class ModelTypeEnum(str, enum.Enum):
    """Types of financial models."""
    PD = "PD"
    LGD = "LGD"
    EAD = "EAD"
    CREDIT_SCORING = "Credit Scoring"
    IFRS_9_ECL = "IFRS 9 ECL"


class ModelStatusEnum(str, enum.Enum):
    """Compliance status of the model."""
    PASS = "PASS"
    WARNING = "WARNING"
    BREACH = "BREACH"


class Model(Base):
    """Core audit record for a financial model."""

    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[ModelTypeEnum] = mapped_column("model_type", SAEnum(ModelTypeEnum), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    portfolio: Mapped[str | None] = mapped_column(String, nullable=True)
    algorithm: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[ModelStatusEnum | None] = mapped_column(SAEnum(ModelStatusEnum), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    versions: Mapped[list[ModelVersion]] = relationship("ModelVersion", back_populates="model", cascade="all, delete-orphan")


class ModelVersion(Base):
    """Lineage node for a Model representing an audit run."""

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("models.id"), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    
    # Store aggregated metrics and gaps as JSON for simplicity
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    gap_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    population_deciles: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    model: Mapped[Model] = relationship("Model", back_populates="versions")
    parent: Mapped[ModelVersion | None] = relationship("ModelVersion", remote_side=[id])
