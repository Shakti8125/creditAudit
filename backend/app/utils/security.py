from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings

logger = logging.getLogger(__name__)


def _generate_default_rsa_keys() -> tuple[str, str]:
    """Generate an ephemeral 2048-bit RSA key pair in PEM format for development/fallback."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


_DEFAULT_PRIVATE_KEY_PEM, _DEFAULT_PUBLIC_KEY_PEM = _generate_default_rsa_keys()


def _get_private_key() -> str:
    """Get the RSA private key in PEM format, unescaping newlines if loaded from env vars."""
    if settings.jwt.private_key and settings.jwt.private_key.strip():
        return settings.jwt.private_key.replace("\\n", "\n")
    return _DEFAULT_PRIVATE_KEY_PEM


def _get_public_key() -> str:
    """Get the RSA public key in PEM format, unescaping newlines if loaded from env vars."""
    if settings.jwt.public_key and settings.jwt.public_key.strip():
        return settings.jwt.public_key.replace("\\n", "\n")
    return _DEFAULT_PUBLIC_KEY_PEM


def hash_password(plain: str) -> str:
    """Hash a plain text password using bcrypt directly."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    tier: str = "FREE",
) -> str:
    """Create a short-lived RS256 access token (1 hour) containing tenant tier for rate limiting."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=1)
    tier_val = tier.value if hasattr(tier, "value") else str(tier)
    role_val = role.value if hasattr(role, "value") else str(role)
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role_val,
        "tier": tier_val,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    return jwt.encode(to_encode, _get_private_key(), algorithm=settings.jwt.algorithm)


def create_refresh_token(user_id: uuid.UUID) -> str:
    """Create a long-lived RS256 refresh token (7 days)."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=7)
    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "refresh",
    }
    return jwt.encode(to_encode, _get_private_key(), algorithm=settings.jwt.algorithm)


def decode_token(token: str) -> dict[str, Any]:
    """Decode a JWT RS256 token and return its payload dictionary."""
    try:
        payload = jwt.decode(
            token,
            _get_public_key(),
            algorithms=[settings.jwt.algorithm],
        )
        return payload
    except jwt.PyJWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise ValueError("Invalid token") from e
