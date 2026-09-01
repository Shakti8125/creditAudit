from __future__ import annotations

import io
import uuid
import jwt
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.db.database import Base, get_db
from app.models.user import User, Tenant, RoleEnum
from app.models.audit import Model, ModelVersion, ModelTypeEnum
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    _get_private_key,
    _get_public_key,
)

from sqlalchemy.pool import StaticPool

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession, expire_on_commit=False
)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_jwt_rs256_cryptographic_verification():
    """Verify RS256 token creation and decoding via PyJWT."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="validator")
    payload = decode_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "validator"
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_jwt_rejects_algorithm_confusion():
    """Verify RS256 validator rejects HS256 forged tokens."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    # Forge HS256 token signed with symmetric secret
    forged_token = jwt.encode(
        {"sub": str(user_id), "tenant_id": str(tenant_id), "type": "access"},
        "symmetric_secret_key_1234567890123456",
        algorithm="HS256",
    )

    with pytest.raises(ValueError) as exc_info:
        decode_token(forged_token)
    assert "Invalid token" in str(exc_info.value)


@pytest.mark.asyncio
async def test_inactive_user_access_rejected():
    """Verify deactivated user account receives 403 Forbidden on authenticated endpoints."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with TestingSessionLocal() as session:
        tenant = Tenant(id=tenant_id, name="Test Tenant")
        user = User(
            id=user_id,
            email="deactivated@tenant.com",
            hashed_password=hash_password("password123"),
            tenant_id=tenant_id,
            role=RoleEnum.ANALYST,
            is_active=False,  # Inactive account
        )
        session.add_all([tenant, user])
        await session.commit()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="validator")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/documents",
            headers={"Authorization": f"Bearer {token}"},
            follow_redirects=True,
        )
        assert response.status_code == 403, f"Expected 403 for inactive user, got {response.status_code}"
        assert "deactivated" in response.json()["detail"]


@pytest.mark.asyncio
async def test_refresh_token_rejected_on_data_endpoints():
    """Verify refresh token (type='refresh') is rejected on protected data endpoints."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with TestingSessionLocal() as session:
        tenant = Tenant(id=tenant_id, name="Test Tenant")
        user = User(
            id=user_id,
            email="active@tenant.com",
            hashed_password=hash_password("password123"),
            tenant_id=tenant_id,
            role=RoleEnum.ANALYST,
            is_active=True,
        )
        session.add_all([tenant, user])
        await session.commit()

    refresh_token = create_refresh_token(user_id=user_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/documents",
            headers={"Authorization": f"Bearer {refresh_token}"},
            follow_redirects=True,
        )
        assert response.status_code == 401, f"Expected 401 for refresh token on data route, got {response.status_code}"
        assert "Invalid token type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_chunked_file_upload_size_limit():
    """Verify uploading a file exceeding MAX_FILE_SIZE returns 413 Payload Too Large."""
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    model_id = uuid.uuid4()
    model_version_id = uuid.uuid4()

    async with TestingSessionLocal() as session:
        tenant = Tenant(id=tenant_id, name="Test Tenant")
        user = User(
            id=user_id,
            email="uploader@tenant.com",
            hashed_password=hash_password("password123"),
            tenant_id=tenant_id,
            role=RoleEnum.ANALYST,
            is_active=True,
        )
        model = Model(
            id=model_id,
            tenant_id=tenant_id,
            user_id=user_id,
            name="Test Model",
            type=ModelTypeEnum.PD,
        )
        model_version = ModelVersion(
            id=model_version_id,
            model_id=model_id,
            version="1.0",
            is_current=True,
        )
        session.add_all([tenant, user, model, model_version])
        await session.commit()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="validator")

    # Generate oversized content (> 50MB)
    # Using a 51MB stream
    oversized_data = b"0" * (51 * 1024 * 1024)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        files = {"file": ("oversized.pdf", io.BytesIO(oversized_data), "application/pdf")}
        data = {"model_version_id": str(model_version_id)}
        response = await client.post(
            "/documents/upload",
            headers={"Authorization": f"Bearer {token}"},
            data=data,
            files=files,
        )
        assert response.status_code == 413, f"Expected 413 for oversized file, got {response.status_code}"


@pytest.mark.asyncio
async def test_jwt_tier_embedding_and_extraction():
    """Verify tier field is encoded into access token and decoded into payload."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()

    token = create_access_token(
        user_id=user_id,
        tenant_id=tenant_id,
        role="validator",
        tier="PROFESSIONAL",
    )
    payload = decode_token(token)

    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "validator"
    assert payload["tier"] == "PROFESSIONAL"
    assert payload["type"] == "access"


def test_rsa_pem_newline_unescaping(monkeypatch):
    """Verify escaped \\n strings from environment variables are properly unescaped."""
    from app.config import settings
    fake_pem = "-----BEGIN PUBLIC KEY-----\\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA\\n-----END PUBLIC KEY-----"
    monkeypatch.setattr(settings.jwt, "public_key", fake_pem)
    
    result = _get_public_key()
    assert "\\n" not in result
    assert "\n" in result
    assert result.startswith("-----BEGIN PUBLIC KEY-----\n")


def test_all_schemas_from_attributes():
    """Verify all Pydantic schemas in app.schemas have from_attributes=True enabled."""
    import inspect
    from pydantic import BaseModel
    import app.schemas as schemas

    for name, obj in inspect.getmembers(schemas):
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
            config = getattr(obj, "model_config", {})
            from_attr = config.get("from_attributes", False) if isinstance(config, dict) else getattr(config, "from_attributes", False)
            assert from_attr is True, f"Schema {name} is missing model_config = ConfigDict(from_attributes=True)"

