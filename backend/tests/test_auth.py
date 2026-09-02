import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from typing import AsyncGenerator

from app.main import app
from app.db.database import Base, get_db

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

async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

import pytest_asyncio

@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def prepare_database():
    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)

@pytest.mark.asyncio
async def test_register_and_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register
        response = await client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "password123", "tenant_name": "Test Tenant"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        
        # Login
        response = await client.post(
            "/auth/login",
            json={"email": "test@example.com", "password": "password123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

@pytest.mark.asyncio
async def test_refresh_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register
        register_response = await client.post(
            "/auth/register",
            json={"email": "refresh@example.com", "password": "password123", "tenant_name": "Test Tenant"}
        )
        refresh_token = register_response.json()["refresh_token"]
        
        # Refresh
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data


@pytest.mark.asyncio
async def test_register_duplicate_email_fails():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # First registration
        response = await client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "password123", "tenant_name": "Tenant 1"}
        )
        assert response.status_code == 200

        # Duplicate registration
        response2 = await client.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "password123", "tenant_name": "Tenant 2"}
        )
        assert response2.status_code == 400
        assert "Email already registered" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_register_password_length_validation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Password too short (<8 chars)
        res_short = await client.post(
            "/auth/register",
            json={"email": "short@example.com", "password": "short", "tenant_name": "Tenant"}
        )
        assert res_short.status_code == 422

        # Password too long (>72 chars)
        res_long = await client.post(
            "/auth/register",
            json={"email": "long@example.com", "password": "a" * 73, "tenant_name": "Tenant"}
        )
        assert res_long.status_code == 422

        # Boundary: 8 chars (valid)
        res_8 = await client.post(
            "/auth/register",
            json={"email": "valid8@example.com", "password": "a" * 8, "tenant_name": "Tenant"}
        )
        assert res_8.status_code == 200

        # Boundary: 72 chars (valid)
        res_72 = await client.post(
            "/auth/register",
            json={"email": "valid72@example.com", "password": "a" * 72, "tenant_name": "Tenant"}
        )
        assert res_72.status_code == 200


@pytest.mark.asyncio
async def test_register_eager_tenant_settings():
    from sqlalchemy import select
    from app.models.system import TenantSettings
    from app.models.user import User

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/register",
            json={"email": "settings_check@example.com", "password": "password123", "tenant_name": "Settings Bank"}
        )
        assert response.status_code == 200

        async with TestingSessionLocal() as session:
            user = (await session.execute(select(User).where(User.email == "settings_check@example.com"))).scalar_one()
            settings = (await session.execute(select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id))).scalar_one_or_none()
            assert settings is not None
            assert settings.strict_zero_trust is True

