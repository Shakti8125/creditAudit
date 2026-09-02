from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.db.database import get_db
from app.models.user import User, Tenant, RoleEnum
from app.models.system import TenantSettings
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshRequest
from app.utils.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=TokenResponse)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new tenant and user."""
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    new_tenant = Tenant(name=request.tenant_name)
    db.add(new_tenant)
    await db.flush()

    new_settings = TenantSettings(tenant_id=new_tenant.id)
    db.add(new_settings)

    new_user = User(
        tenant_id=new_tenant.id,
        email=request.email,
        hashed_password=hash_password(request.password),
        role=RoleEnum.ADMIN
    )
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Email already registered")

    await db.refresh(new_user)

    tier_val = new_tenant.tier.value if hasattr(new_tenant.tier, "value") else str(new_tenant.tier)
    access_token = create_access_token(new_user.id, new_tenant.id, new_user.role.value, tier=tier_val)
    refresh_token = create_refresh_token(new_user.id)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login and get tokens."""
    result = await db.execute(select(User).options(selectinload(User.tenant)).where(User.email == request.email))
    user = result.scalars().first()
    
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated"
        )
        
    tier_val = user.tenant.tier.value if user.tenant and hasattr(user.tenant, "tier") else "FREE"
    access_token = create_access_token(user.id, user.tenant_id, user.role.value, tier=tier_val)
    refresh_token = create_refresh_token(user.id)

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)

@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Issue a new access token from a refresh token."""
    try:
        payload = decode_token(request.refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("Invalid token type")
    except Exception as e:
        logger.warning(f"Failed to decode refresh token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )
        
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
    try:
        user_id = uuid.UUID(str(user_id_str))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID format"
        )
        
    result = await db.execute(select(User).options(selectinload(User.tenant)).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated"
        )
        
    tier_val = user.tenant.tier.value if user.tenant and hasattr(user.tenant, "tier") else "FREE"
    access_token = create_access_token(user.id, user.tenant_id, user.role.value, tier=tier_val)
    new_refresh_token = create_refresh_token(user.id)

    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)

