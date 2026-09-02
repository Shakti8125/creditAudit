from __future__ import annotations

import uuid
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Schema for user registration request."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72, description="Password between 8 and 72 characters")
    tenant_name: str


class LoginRequest(BaseModel):
    """Schema for user login request."""

    model_config = ConfigDict(from_attributes=True)

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Schema for token refresh request."""

    model_config = ConfigDict(from_attributes=True)

    refresh_token: str


class TokenResponse(BaseModel):
    """Schema for JWT authentication response."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600


class TokenPayload(BaseModel):
    """Schema for decoded JWT token payload."""

    model_config = ConfigDict(from_attributes=True)

    sub: uuid.UUID
    tenant_id: uuid.UUID | None = None
    role: str | None = None
    tier: str | None = "FREE"
    exp: int
    type: str
