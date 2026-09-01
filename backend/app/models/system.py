from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Uuid, JSON, Float, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.models.user import _utc_now


class TenantSettings(Base):
    """Tenant-specific settings and thresholds."""

    __tablename__ = "tenant_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, unique=True, nullable=False)
    
    gini_tolerance: Mapped[float] = mapped_column(Float, default=0.05, nullable=False)
    psi_warning_threshold: Mapped[float] = mapped_column(Float, default=0.1, nullable=False)
    psi_breach_threshold: Mapped[float] = mapped_column(Float, default=0.25, nullable=False)
    auto_mask_bank: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_mask_borrower: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_mask_location: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    strict_zero_trust: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    min_observation_months: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, onupdate=_utc_now, nullable=False)


class NotificationTypeEnum(str, enum.Enum):
    """Notification types."""
    PASS = "PASS"
    WARNING = "WARNING"
    BREACH = "BREACH"
    INFO = "INFO"


class Notification(Base):
    """Alerts for users."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("models.id"), index=True, nullable=True)
    
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[NotificationTypeEnum] = mapped_column("notification_type", SAEnum(NotificationTypeEnum), default=NotificationTypeEnum.INFO, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)


class RegulatoryStandard(Base):
    """Catalog of regulatory standards."""

    __tablename__ = "regulatory_standards"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    authority: Mapped[str] = mapped_column(String, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String, nullable=False)
    clauses_json: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    effective_date: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)
