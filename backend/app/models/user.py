from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


class TierEnum(str, enum.Enum):
    """Subscription tier enumeration."""

    FREE = "FREE"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class RoleEnum(str, enum.Enum):
    """User role enumeration."""

    ANALYST = "ANALYST"
    SENIOR_RISK_OFFICER = "SENIOR_RISK_OFFICER"
    COMPLIANCE_AUDITOR = "COMPLIANCE_AUDITOR"
    ADMIN = "ADMIN"


def _utc_now() -> datetime:
    """Return the current timezone-naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    """Tenant model for multi-tenancy."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[TierEnum] = mapped_column(SAEnum(TierEnum), default=TierEnum.FREE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    users: Mapped[list[User]] = relationship("User", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    """User model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    
    # Profile fields
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    division: Mapped[str | None] = mapped_column(String, nullable=True)
    security_clearance: Mapped[str | None] = mapped_column(String, nullable=True)
    
    role: Mapped[RoleEnum] = mapped_column(SAEnum(RoleEnum), default=RoleEnum.ANALYST, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now, nullable=False)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="users")
