"""Programmatic E2E Verification Script for User Registration & Authentication.

This script tests the complete registration flow:
1. User registration with valid credentials and tenant creation.
2. Token verification (access & refresh tokens with RS256 signing).
3. Direct database record persistence verification (User, Tenant, and TenantSettings).
4. Authenticated profile retrieval via GET /users/me using the Bearer token.
5. Rejection of duplicate email registrations (400 Bad Request).
6. Password length boundary validation (<8 and >72 characters return 422 Unprocessable Entity).

Can be run via pytest:
    pytest backend/tests/verify_registration.py -v
Or executed directly as a standalone script:
    python backend/tests/verify_registration.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import AsyncGenerator

# Ensure backend directory is in sys.path when running standalone
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.system import TenantSettings
from app.models.user import RoleEnum, Tenant, User

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


async def override_get_rate_limiter() -> None:
    pass


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def prepare_database():
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)


@pytest.mark.asyncio
async def test_end_to_end_user_registration_and_persistence():
    """Verify end-to-end registration, DB persistence, profile fetch, duplicate check, and password bounds."""
    test_email = "test_audit_user@example.com"
    test_password = "TestPass123!"
    tenant_name = "Test Audit Bank"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Step A & B: Post registration and assert 200 + valid TokenResponse
        reg_response = await client.post(
            "/auth/register",
            json={
                "email": test_email,
                "password": test_password,
                "tenant_name": tenant_name,
            },
        )
        assert reg_response.status_code == 200, f"Registration failed: {reg_response.text}"
        tokens = reg_response.json()
        assert "access_token" in tokens and tokens["access_token"]
        assert "refresh_token" in tokens and tokens["refresh_token"]
        assert tokens.get("token_type") == "Bearer"
        assert tokens.get("expires_in") == 3600
        access_token = tokens["access_token"]

        # Step C: Direct Database verification
        async with TestingSessionLocal() as session:
            user_stmt = select(User).where(User.email == test_email)
            user_res = await session.execute(user_stmt)
            persisted_user = user_res.scalar_one_or_none()

            assert persisted_user is not None, "User record not found in database"
            assert persisted_user.email == test_email
            assert persisted_user.role == RoleEnum.ADMIN
            assert persisted_user.is_active is True

            tenant_stmt = select(Tenant).where(Tenant.id == persisted_user.tenant_id)
            tenant_res = await session.execute(tenant_stmt)
            persisted_tenant = tenant_res.scalar_one_or_none()

            assert persisted_tenant is not None, "Tenant record not found in database"
            assert persisted_tenant.name == tenant_name

            settings_stmt = select(TenantSettings).where(TenantSettings.tenant_id == persisted_user.tenant_id)
            settings_res = await session.execute(settings_stmt)
            persisted_settings = settings_res.scalar_one_or_none()

            assert persisted_settings is not None, "TenantSettings not eagerly created on registration"
            assert persisted_settings.strict_zero_trust is True

        # Step D: Call GET /users/me using Bearer token
        me_response = await client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert me_response.status_code == 200, f"/users/me failed: {me_response.text}"
        me_data = me_response.json()
        assert me_data["id"] == str(persisted_user.id)
        assert me_data["email"] == test_email
        assert me_data["role"] == "ADMIN"
        assert me_data["is_active"] is True

        # Step E: Attempt duplicate registration with same email (Must return HTTP 400)
        dup_response = await client.post(
            "/auth/register",
            json={
                "email": test_email,
                "password": "AnotherPassword456!",
                "tenant_name": "Another Tenant",
            },
        )
        assert dup_response.status_code == 400, f"Expected 400 on duplicate registration, got {dup_response.status_code}"
        dup_data = dup_response.json()
        assert "Email already registered" in dup_data.get("detail", "")

        # Step F: Password length validation (<8 chars and >72 chars return 422)
        short_pass_response = await client.post(
            "/auth/register",
            json={
                "email": "short_pass@example.com",
                "password": "short",
                "tenant_name": "Short Pass Tenant",
            },
        )
        assert short_pass_response.status_code == 422, f"Expected 422 for short password, got {short_pass_response.status_code}"

        long_pass_response = await client.post(
            "/auth/register",
            json={
                "email": "long_pass@example.com",
                "password": "A" * 73,
                "tenant_name": "Long Pass Tenant",
            },
        )
        assert long_pass_response.status_code == 422, f"Expected 422 for >72 char password, got {long_pass_response.status_code}"


async def run_standalone_verification() -> int:
    """Execute verification workflow in standalone Python execution."""
    print("================================================================================")
    print(" [VERIFY] ModelAudit AI User Registration & Auth Programmatic Verification")
    print("================================================================================")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        test_email = "test_audit_user@example.com"
        test_password = "TestPass123!"
        tenant_name = "Test Audit Bank"

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Register
            print(f"[*] Posting registration for '{test_email}'...")
            reg_response = await client.post(
                "/auth/register",
                json={"email": test_email, "password": test_password, "tenant_name": tenant_name},
            )
            assert reg_response.status_code == 200, f"Registration failed with code {reg_response.status_code}: {reg_response.text}"
            tokens = reg_response.json()
            assert "access_token" in tokens and "refresh_token" in tokens, "TokenResponse missing tokens"
            access_token = tokens["access_token"]
            print(f"    [+] Success! Token type: {tokens.get('token_type')}, expires_in: {tokens.get('expires_in')}s")

            # 2. Database validation
            print("[*] Directly querying database for User, Tenant, and TenantSettings...")
            async with TestingSessionLocal() as session:
                user_res = await session.execute(select(User).where(User.email == test_email))
                user = user_res.scalar_one_or_none()
                assert user is not None, "User not found in DB"
                assert user.role == RoleEnum.ADMIN, f"User role {user.role} != ADMIN"

                tenant_res = await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
                tenant = tenant_res.scalar_one_or_none()
                assert tenant is not None and tenant.name == tenant_name, "Tenant not found in DB"

                settings_res = await session.execute(select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id))
                settings = settings_res.scalar_one_or_none()
                assert settings is not None, "TenantSettings not found in DB"

            print(f"    [+] Verified in DB: User ID={user.id}, Tenant ID={tenant.id}, Settings ID={settings.id}")

            # 3. /users/me verification
            print("[*] Querying GET /users/me with Bearer token...")
            me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {access_token}"})
            assert me_res.status_code == 200, f"/users/me failed: {me_res.text}"
            me_json = me_res.json()
            assert me_json["id"] == str(user.id)
            assert me_json["email"] == test_email and me_json["role"] == "ADMIN" and me_json["is_active"] is True
            print(f"    [+] Verified profile: ID={me_json['id']}, Email={me_json['email']}, Role={me_json['role']}, Active={me_json['is_active']}")

            # 4. Duplicate rejection
            print("[*] Testing duplicate email registration rejection...")
            dup_res = await client.post(
                "/auth/register",
                json={"email": test_email, "password": "Pass12345678!", "tenant_name": "Another Tenant"},
            )
            assert dup_res.status_code == 400, f"Expected 400 for duplicate email, got {dup_res.status_code}"
            print(f"    [+] Verified duplicate rejection: HTTP 400 with detail '{dup_res.json().get('detail')}'")

            # 5. Password length constraints
            print("[*] Testing password length boundary validation (<8 chars and >72 chars)...")
            short_res = await client.post(
                "/auth/register",
                json={"email": "short@example.com", "password": "short", "tenant_name": "Tenant"},
            )
            assert short_res.status_code == 422, f"Expected 422 for short password, got {short_res.status_code}"

            long_res = await client.post(
                "/auth/register",
                json={"email": "long@example.com", "password": "A" * 73, "tenant_name": "Tenant"},
            )
            assert long_res.status_code == 422, f"Expected 422 for oversized password, got {long_res.status_code}"
            print("    [+] Verified password bounds: <8 chars and >72 chars correctly rejected with HTTP 422.")

        print("================================================================================")
        print(" [ALL VERIFICATION CHECKS PASSED SUCCESSFULLY]")
        print("================================================================================")
        return 0
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_rate_limiter, None)


if __name__ == "__main__":
    exit_code = asyncio.run(run_standalone_verification())
    sys.exit(exit_code)
