from __future__ import annotations

import uuid
from typing import AsyncGenerator
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from sqlalchemy import select, func

from app.main import app
from app.db.database import Base, get_db
from app.models.user import User, Tenant, RoleEnum, TierEnum
from app.models.system import TenantSettings
from app.utils.security import decode_token

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

@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def prepare_database():
    app.dependency_overrides[get_db] = override_get_db
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)


# ============================================================================
# 1. Adversarial Email Validation Test Suite
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_email",
    [
        "",                                 # Empty string
        "plainaddress",                     # Missing @ and domain
        "@missingusername.com",             # Missing username
        "username@",                        # Missing domain
        "username@.com",                    # Missing domain label
        "username@com",                     # Missing TLD dot
        "username@domain..com",             # Double dots in domain
        "username space@domain.com",        # Space in username
        "username@domain space.com",        # Space in domain
        "username@@domain.com",             # Double @ symbol
        "user@example@another.com",         # Multiple @ symbols
        "user;name@domain.com",             # Semicolon in username
        "<script>alert(1)</script>@x.com",  # HTML tags in username
        ".username@domain.com",             # Leading dot in local part
        "username.@domain.com",             # Trailing dot in local part
        "user..name@domain.com",            # Consecutive dots in local part
        "user@.domain.com",                 # Leading dot in domain
        "user@domain..org",                 # Double dot in domain
    ],
)
async def test_adversarial_malformed_emails_rejected(malformed_email: str):
    """Test that various malformed, invalid, and hostile email formats return HTTP 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Check initial DB counts
        async with TestingSessionLocal() as session:
            initial_users = (await session.execute(select(func.count(User.id)))).scalar_one()
            initial_tenants = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
            initial_settings = (await session.execute(select(func.count(TenantSettings.id)))).scalar_one()

        response = await client.post(
            "/auth/register",
            json={
                "email": malformed_email,
                "password": "ValidPassword123!",
                "tenant_name": "Adversarial Bank",
            },
        )
        assert response.status_code == 422, f"Expected 422 for malformed email '{malformed_email}', got {response.status_code}"
        
        # Verify 0 database side effects
        async with TestingSessionLocal() as session:
            assert (await session.execute(select(func.count(User.id)))).scalar_one() == initial_users
            assert (await session.execute(select(func.count(Tenant.id)))).scalar_one() == initial_tenants
            assert (await session.execute(select(func.count(TenantSettings.id)))).scalar_one() == initial_settings


@pytest.mark.asyncio
async def test_adversarial_non_string_email_rejected():
    """Test non-string/null email field inputs."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Null email
        res_null = await client.post(
            "/auth/register",
            json={"email": None, "password": "ValidPassword123!", "tenant_name": "Bank"},
        )
        assert res_null.status_code == 422

        # Integer email
        res_int = await client.post(
            "/auth/register",
            json={"email": 123456, "password": "ValidPassword123!", "tenant_name": "Bank"},
        )
        assert res_int.status_code == 422

        # Missing email field entirely
        res_missing = await client.post(
            "/auth/register",
            json={"password": "ValidPassword123!", "tenant_name": "Bank"},
        )
        assert res_missing.status_code == 422


# ============================================================================
# 2. Adversarial Password Boundary & Edge Case Test Suite
# ============================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_password,desc",
    [
        ("", "0-character empty string"),
        ("a", "1 character"),
        ("1234567", "7 characters (1 below min)"),
        ("a" * 73, "73 characters (1 above max 72)"),
        ("a" * 100, "100 characters"),
        ("a" * 1000, "1000 characters"),
    ],
)
async def test_adversarial_password_length_boundaries_rejected(invalid_password: str, desc: str):
    """Test passwords outside [8, 72] length boundary fail with HTTP 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Initial DB count
        async with TestingSessionLocal() as session:
            initial_users = (await session.execute(select(func.count(User.id)))).scalar_one()

        response = await client.post(
            "/auth/register",
            json={
                "email": f"pwtest_{len(invalid_password)}@example.com",
                "password": invalid_password,
                "tenant_name": "Bank",
            },
        )
        assert response.status_code == 422, f"Failed boundary check for {desc}: expected 422, got {response.status_code}"

        # DB unaffected
        async with TestingSessionLocal() as session:
            assert (await session.execute(select(func.count(User.id)))).scalar_one() == initial_users


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "valid_password,desc",
    [
        ("12345678", "Exactly 8 characters (min bound)"),
        ("123456789", "9 characters"),
        ("a" * 71, "71 characters"),
        ("a" * 72, "Exactly 72 characters (max bound)"),
        ("P@ssw0rd!#$%", "Special symbols"),
        ("Pass word 123", "Internal whitespace"),
        ("Päßwörd-123", "Unicode Latin-1 chars within 72 bytes"),
    ],
)
async def test_adversarial_password_valid_boundaries_and_login(valid_password: str, desc: str):
    """Test passwords within [8, 72] length boundary succeed and can authenticate."""
    email = f"valid_pw_{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Register
        res_reg = await client.post(
            "/auth/register",
            json={
                "email": email,
                "password": valid_password,
                "tenant_name": "Valid Boundary Bank",
            },
        )
        assert res_reg.status_code == 200, f"Registration failed for valid password ({desc}): {res_reg.text}"
        reg_data = res_reg.json()
        assert "access_token" in reg_data
        assert "refresh_token" in reg_data

        # 2. Login with the exact same boundary password
        res_login = await client.post(
            "/auth/login",
            json={
                "email": email,
                "password": valid_password,
            },
        )
        assert res_login.status_code == 200, f"Login failed with registered password ({desc}): {res_login.text}"
        login_data = res_login.json()
        assert "access_token" in login_data

        # 3. Decode access token and verify payload
        payload = decode_token(login_data["access_token"])
        assert payload["role"] == "ADMIN"
        assert payload["tier"] == "FREE"
        assert "sub" in payload
        assert "tenant_id" in payload


# ============================================================================
# 3. Tenant Name Boundary & Injection Test Suite
# ============================================================================
@pytest.mark.asyncio
async def test_adversarial_tenant_name_missing_or_null():
    """Test missing or null tenant_name."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Missing tenant_name
        res_missing = await client.post(
            "/auth/register",
            json={"email": "tenant_missing@example.com", "password": "Password123!"},
        )
        assert res_missing.status_code == 422

        # Null tenant_name
        res_null = await client.post(
            "/auth/register",
            json={"email": "tenant_null@example.com", "password": "Password123!", "tenant_name": None},
        )
        assert res_null.status_code == 422


@pytest.mark.asyncio
async def test_adversarial_tenant_name_empty_and_whitespace():
    """Test behavior of empty and whitespace-only tenant names."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Empty string tenant_name
        res_empty = await client.post(
            "/auth/register",
            json={"email": "tenant_empty@example.com", "password": "Password123!", "tenant_name": ""},
        )
        if res_empty.status_code == 200:
            async with TestingSessionLocal() as session:
                user = (await session.execute(select(User).where(User.email == "tenant_empty@example.com"))).scalar_one()
                tenant = (await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one()
                assert tenant.name == ""
        else:
            assert res_empty.status_code == 422

        # Whitespace-only tenant_name
        res_ws = await client.post(
            "/auth/register",
            json={"email": "tenant_ws@example.com", "password": "Password123!", "tenant_name": "   "},
        )
        if res_ws.status_code == 200:
            async with TestingSessionLocal() as session:
                user = (await session.execute(select(User).where(User.email == "tenant_ws@example.com"))).scalar_one()
                tenant = (await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one()
                assert tenant.name == "   "
        else:
            assert res_ws.status_code == 422


@pytest.mark.asyncio
async def test_adversarial_tenant_name_sql_and_xss_safety():
    """Test SQL injection and XSS payloads in tenant_name are safely handled as literals."""
    sql_injection_name = "Acme Bank'; DROP TABLE tenants; --"
    xss_payload_name = "<script>alert('xss')</script><img src=x onerror=alert(1)>"
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # SQL Injection attempt
        res_sql = await client.post(
            "/auth/register",
            json={
                "email": "sql_inject@example.com",
                "password": "Password123!",
                "tenant_name": sql_injection_name,
            },
        )
        assert res_sql.status_code == 200
        async with TestingSessionLocal() as session:
            user = (await session.execute(select(User).where(User.email == "sql_inject@example.com"))).scalar_one()
            tenant = (await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one()
            assert tenant.name == sql_injection_name
            # Ensure tables still exist
            tenant_count = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
            assert tenant_count >= 1

        # XSS Payload
        res_xss = await client.post(
            "/auth/register",
            json={
                "email": "xss_payload@example.com",
                "password": "Password123!",
                "tenant_name": xss_payload_name,
            },
        )
        assert res_xss.status_code == 200
        async with TestingSessionLocal() as session:
            user = (await session.execute(select(User).where(User.email == "xss_payload@example.com"))).scalar_one()
            tenant = (await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))).scalar_one()
            assert tenant.name == xss_payload_name


# ============================================================================
# 4. Database Transaction Atomicity & Orphan Prevention Test Suite
# ============================================================================
@pytest.mark.asyncio
async def test_no_orphaned_tenant_or_settings_on_duplicate_email_rejection():
    """Verify that when a duplicate email is rejected (HTTP 400), NO orphaned Tenant or TenantSettings are created."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. First registration (success)
        res1 = await client.post(
            "/auth/register",
            json={
                "email": "primary_user@example.com",
                "password": "SecurePassword123!",
                "tenant_name": "Primary Tenant",
            },
        )
        assert res1.status_code == 200

        # Snapshot DB counts
        async with TestingSessionLocal() as session:
            users_before = (await session.execute(select(func.count(User.id)))).scalar_one()
            tenants_before = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
            settings_before = (await session.execute(select(func.count(TenantSettings.id)))).scalar_one()
            assert users_before == 1
            assert tenants_before == 1
            assert settings_before == 1

        # 2. Duplicate registration attempt with a DIFFERENT tenant name
        res2 = await client.post(
            "/auth/register",
            json={
                "email": "primary_user@example.com",
                "password": "DifferentPassword123!",
                "tenant_name": "Orphan Attempt Tenant",
            },
        )
        assert res2.status_code == 400
        assert "Email already registered" in res2.json()["detail"]

        # 3. Verify counts are unchanged and no 'Orphan Attempt Tenant' exists
        async with TestingSessionLocal() as session:
            users_after = (await session.execute(select(func.count(User.id)))).scalar_one()
            tenants_after = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
            settings_after = (await session.execute(select(func.count(TenantSettings.id)))).scalar_one()

            assert users_after == users_before, "User table count changed on duplicate rejection!"
            assert tenants_after == tenants_before, "Tenant was orphaned on duplicate email rejection!"
            assert settings_after == settings_before, "TenantSettings was orphaned on duplicate rejection!"

            orphan_tenant = (await session.execute(select(Tenant).where(Tenant.name == "Orphan Attempt Tenant"))).scalar_one_or_none()
            assert orphan_tenant is None, "Orphan tenant record was persisted in database!"


@pytest.mark.asyncio
async def test_transaction_rollback_on_commit_integrity_error():
    """Verify that if an IntegrityError occurs at commit time (e.g. race condition), all flushed records are rolled back."""
    from unittest.mock import patch
    from sqlalchemy.exc import IntegrityError

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Snapshot initial counts
        async with TestingSessionLocal() as session:
            initial_users = (await session.execute(select(func.count(User.id)))).scalar_one()
            initial_tenants = (await session.execute(select(func.count(Tenant.id)))).scalar_one()
            initial_settings = (await session.execute(select(func.count(TenantSettings.id)))).scalar_one()

        # Simulate IntegrityError on db.commit
        with patch.object(AsyncSession, "commit", side_effect=IntegrityError("Simulated race duplicate", params={}, orig=Exception())):
            response = await client.post(
                "/auth/register",
                json={
                    "email": "race_condition@example.com",
                    "password": "SecurePassword123!",
                    "tenant_name": "Race Condition Bank",
                },
            )
            assert response.status_code == 400
            assert "Email already registered" in response.json()["detail"]

        # Verify DB rollback: no users, tenants, or settings were persisted
        async with TestingSessionLocal() as session:
            assert (await session.execute(select(func.count(User.id)))).scalar_one() == initial_users
            assert (await session.execute(select(func.count(Tenant.id)))).scalar_one() == initial_tenants
            assert (await session.execute(select(func.count(TenantSettings.id)))).scalar_one() == initial_settings

            race_tenant = (await session.execute(select(Tenant).where(Tenant.name == "Race Condition Bank"))).scalar_one_or_none()
            assert race_tenant is None, "Tenant flushed before rollback was not rolled back!"
