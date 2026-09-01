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
