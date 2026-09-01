from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import TokenPayload
from app.utils.security import decode_token

security = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> TokenPayload:
    """Canonical dependency to extract, decode and validate the JWT token and active user state."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload_dict = decode_token(credentials.credentials)
    except HTTPException:
        raise
    except Exception as exc:
        raise credentials_exception from exc

    if payload_dict.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload_dict.get("sub")
    if not user_id_str:
        raise credentials_exception

    try:
        user_id = uuid.UUID(str(user_id_str))
    except (ValueError, TypeError) as exc:
        raise credentials_exception from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    tenant_id_val = user.tenant_id if user.tenant_id else (
        uuid.UUID(str(payload_dict["tenant_id"])) if payload_dict.get("tenant_id") else None
    )
    role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
    tier_val = str(payload_dict.get("tier", "FREE"))

    return TokenPayload(
        sub=user.id,
        tenant_id=tenant_id_val,
        role=role_val,
        tier=tier_val,
        exp=int(payload_dict.get("exp", 0)),
        type=str(payload_dict.get("type", "access")),
    )

