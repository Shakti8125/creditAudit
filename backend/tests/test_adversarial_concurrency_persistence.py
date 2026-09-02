"""Adversarial Challenge Test Suite: Concurrency, Session Handling, Token Validation & Multi-Tenancy Persistence.

This test suite executes empirical adversarial challenges against the ModelAudit AI
FastAPI application and database layer:
1. Concurrency: High-concurrency simultaneous duplicate registrations with identical email.
2. Concurrency: High-concurrency simultaneous distinct registrations ensuring tenant isolation.
3. Token Tampering: Signature tampering, payload manipulation, foreign RSA keys, alg confusion (HS256, none).
4. Token Edge Cases: Expired tokens, refresh token misuse on data routes, nonexistent sub, invalid sub UUID, deactivated users.
5. Multi-Tenancy: Tenant ID isolation, default TenantSettings eager persistence, independent settings mutations.
6. Cross-Tenant Isolation: Dashboard metrics isolation between distinct tenants.
7. DB Persistence: Transaction commit verification, password hashing integrity, and queryability across isolated sessions.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_current_user
from app.config import settings
from app.db.database import Base, get_db
from app.main import app
from app.middleware.rate_limiter import get_rate_limiter
from app.models.audit import Model, ModelStatusEnum, ModelTypeEnum
from app.models.system import TenantSettings
from app.models.user import RoleEnum, Tenant, User
from app.utils.security import (
    _get_private_key,
    _get_public_key,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def prepare_database():
    """Create a temporary isolated SQLite database file per test with NullPool for true multi-connection concurrency."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, f"test_adv_{uuid.uuid4().hex}.db")
    db_url = f"sqlite+aiosqlite:///{db_path}"

    test_engine = create_async_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    SessionLocal = async_sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with SessionLocal() as session:
            yield session

    async def override_get_rate_limiter() -> None:
        pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_rate_limiter] = override_get_rate_limiter

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Attach to test context
    yield SessionLocal

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_rate_limiter, None)

    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass


# ==============================================================================
# 1. CONCURRENCY & RACE CONDITIONS
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_simultaneous_duplicate_registrations(prepare_database):
    """Challenge: 10 concurrent requests simultaneously register the exact same email.
    
    Expected:
    - Exactly 1 request succeeds with HTTP 200 (TokenResponse).
    - Exactly 9 requests fail with HTTP 400 ('Email already registered').
    - Database contains exactly 1 User, 1 Tenant, and 1 TenantSettings.
    - No orphaned Tenant or TenantSettings rows left in the database.
    """
    SessionLocal = prepare_database
    race_email = "concurrent_race_user@example.com"
    concurrency_count = 10

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tasks = [
            client.post(
                "/auth/register",
                json={
                    "email": race_email,
                    "password": f"Password{i}!12345",
                    "tenant_name": f"Concurrent Bank {i}",
                },
            )
            for i in range(concurrency_count)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=False)

        status_codes = [r.status_code for r in responses]
        success_responses = [r for r in responses if r.status_code == 200]
        duplicate_responses = [r for r in responses if r.status_code == 400]

        assert len(success_responses) == 1, (
            f"Expected exactly 1 success out of {concurrency_count} concurrent registrations, "
            f"got {len(success_responses)}. Status codes: {status_codes}"
        )
        assert len(duplicate_responses) == concurrency_count - 1, (
            f"Expected {concurrency_count - 1} duplicate rejections with HTTP 400, "
            f"got {len(duplicate_responses)}. Status codes: {status_codes}"
        )

        for dup_r in duplicate_responses:
            assert "Email already registered" in dup_r.json().get("detail", "")

        # Direct DB verification: no orphaned records
        async with SessionLocal() as session:
            users = (await session.execute(select(User).where(User.email == race_email))).scalars().all()
            assert len(users) == 1, f"Expected 1 persisted user, found {len(users)}"

            winning_user = users[0]
            tenants = (await session.execute(select(Tenant))).scalars().all()
            assert len(tenants) == 1, f"Expected exactly 1 tenant, found {len(tenants)} (possible orphaned tenants)"
            assert tenants[0].id == winning_user.tenant_id

            settings_records = (await session.execute(select(TenantSettings))).scalars().all()
            assert len(settings_records) == 1, (
                f"Expected exactly 1 TenantSettings, found {len(settings_records)} (possible orphaned settings)"
            )
            assert settings_records[0].tenant_id == winning_user.tenant_id


@pytest.mark.asyncio
async def test_concurrent_distinct_registrations_tenant_isolation(prepare_database):
    """Challenge: 10 concurrent requests simultaneously register distinct users.
    
    Expected:
    - All 10 requests succeed with HTTP 200.
    - Database contains 10 distinct Users, 10 distinct Tenants, 10 distinct TenantSettings.
    - All tenant_ids are mutually unique (zero cross-tenant collisions).
    """
    SessionLocal = prepare_database
    concurrency_count = 10

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tasks = [
            client.post(
                "/auth/register",
                json={
                    "email": f"tenant_user_{i}@bank{i}.com",
                    "password": f"Password{i}!12345",
                    "tenant_name": f"Isolated Bank {i}",
                },
            )
            for i in range(concurrency_count)
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=False)

        assert all(r.status_code == 200 for r in responses), (
            f"Not all concurrent distinct registrations succeeded: {[r.status_code for r in responses]}"
        )

        async with SessionLocal() as session:
            users = (await session.execute(select(User))).scalars().all()
            assert len(users) == concurrency_count

            tenants = (await session.execute(select(Tenant))).scalars().all()
            assert len(tenants) == concurrency_count

            settings_records = (await session.execute(select(TenantSettings))).scalars().all()
            assert len(settings_records) == concurrency_count

            user_tenant_ids = {u.tenant_id for u in users}
            tenant_ids = {t.id for t in tenants}
            settings_tenant_ids = {s.tenant_id for s in settings_records}

            assert len(user_tenant_ids) == concurrency_count, "Collision detected in user tenant IDs"
            assert user_tenant_ids == tenant_ids, "User tenant IDs do not match Tenant IDs"
            assert settings_tenant_ids == tenant_ids, "Settings tenant IDs do not match Tenant IDs"


# ==============================================================================
# 2. TOKEN VALIDITY & ADVERSARIAL TAMPERING ON GET /users/me
# ==============================================================================

@pytest.mark.asyncio
async def test_tampered_signature_rejected_on_users_me(prepare_database):
    """Challenge: Tamper with the cryptographic signature of a valid RS256 token."""
    test_email = "tamper_sig@example.com"
    test_password = "SecurePassword123!"
    tenant_name = "Tamper Sig Bank"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg_res = await client.post(
            "/auth/register",
            json={"email": test_email, "password": test_password, "tenant_name": tenant_name},
        )
        assert reg_res.status_code == 200
        valid_token = reg_res.json()["access_token"]

        # Split into header.payload.signature
        parts = valid_token.split(".")
        assert len(parts) == 3

        # Mutate signature by flipping characters in the signature segment
        tampered_sig = parts[2][:-4] + "XXXX" if parts[2][-4:] != "XXXX" else parts[2][:-4] + "YYYY"
        tampered_token = f"{parts[0]}.{parts[1]}.{tampered_sig}"

        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {tampered_token}"})
        assert me_res.status_code == 401, f"Expected 401 for tampered signature, got {me_res.status_code}"
        assert me_res.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_tampered_payload_rejected_on_users_me(prepare_database):
    """Challenge: Tamper with the payload JSON (privilege escalation attempt) without re-signing."""
    test_email = "tamper_payload@example.com"
    test_password = "SecurePassword123!"
    tenant_name = "Tamper Payload Bank"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg_res = await client.post(
            "/auth/register",
            json={"email": test_email, "password": test_password, "tenant_name": tenant_name},
        )
        assert reg_res.status_code == 200
        valid_token = reg_res.json()["access_token"]

        parts = valid_token.split(".")
        # Pad payload base64 if needed
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload_json = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        
        # Tamper payload: elevate tier and change role
        payload_json["tier"] = "ENTERPRISE_UNLIMITED"
        payload_json["role"] = "SUPERADMIN"
        
        tampered_payload_b64 = base64.urlsafe_b64encode(
            json.dumps(payload_json).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        
        tampered_token = f"{parts[0]}.{tampered_payload_b64}.{parts[2]}"

        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {tampered_token}"})
        assert me_res.status_code == 401, f"Expected 401 for tampered payload, got {me_res.status_code}"


@pytest.mark.asyncio
async def test_forged_foreign_rsa_key_rejected(prepare_database):
    """Challenge: Sign a payload with an attacker-controlled RSA 2048 key pair."""
    foreign_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign_private_pem = foreign_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    attacker_user_id = uuid.uuid4()
    attacker_tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    
    forged_payload = {
        "sub": str(attacker_user_id),
        "tenant_id": str(attacker_tenant_id),
        "role": "ADMIN",
        "tier": "ENTERPRISE",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "type": "access",
    }
    forged_token = jwt.encode(forged_payload, foreign_private_pem, algorithm="RS256")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {forged_token}"})
        assert me_res.status_code == 401, f"Expected 401 for foreign RSA key, got {me_res.status_code}"


@pytest.mark.asyncio
async def test_algorithm_confusion_and_none_alg_rejected(prepare_database):
    """Challenge: Attempt algorithm confusion attacks (HS256 with symmetric key, 'none' algorithm)."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # 1. HS256 signed with symmetric secret key
    hs256_token = jwt.encode(
        {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": "ADMIN",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "type": "access",
        },
        "attacker_symmetric_secret_key_123456789",
        algorithm="HS256",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res_hs256 = await client.get("/users/me", headers={"Authorization": f"Bearer {hs256_token}"})
        assert res_hs256.status_code == 401, f"Expected 401 for HS256 confusion token, got {res_hs256.status_code}"

        # 2. 'none' algorithm token
        header_none = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode("utf-8").rstrip("=")
        payload_none = base64.urlsafe_b64encode(
            json.dumps({
                "sub": str(user_id),
                "tenant_id": str(tenant_id),
                "role": "ADMIN",
                "exp": int((now + timedelta(hours=1)).timestamp()),
                "type": "access",
            }).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        none_token = f"{header_none}.{payload_none}."

        res_none = await client.get("/users/me", headers={"Authorization": f"Bearer {none_token}"})
        assert res_none.status_code == 401, f"Expected 401 for alg=none token, got {res_none.status_code}"


@pytest.mark.asyncio
async def test_expired_access_token_rejected(prepare_database):
    """Challenge: Attempt GET /users/me using an expired access token."""
    user_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Mint expired token (expired 10 minutes ago)
    expired_payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": "ADMIN",
        "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": int((now - timedelta(minutes=10)).timestamp()),
        "type": "access",
    }
    expired_token = jwt.encode(expired_payload, _get_private_key(), algorithm="RS256")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert me_res.status_code == 401, f"Expected 401 for expired token, got {me_res.status_code}"


@pytest.mark.asyncio
async def test_refresh_token_rejected_on_users_me(prepare_database):
    """Challenge: Present a valid refresh token (type='refresh') to GET /users/me.
    
    Expected: Rejection with HTTP 401 and 'Invalid token type'.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg_res = await client.post(
            "/auth/register",
            json={"email": "refresh_user@bank.com", "password": "Password123!", "tenant_name": "Refresh Bank"},
        )
        assert reg_res.status_code == 200
        refresh_token = reg_res.json()["refresh_token"]

        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {refresh_token}"})
        assert me_res.status_code == 401, f"Expected 401 for refresh token on /users/me, got {me_res.status_code}"
        assert "Invalid token type" in me_res.json().get("detail", "")


@pytest.mark.asyncio
async def test_nonexistent_user_id_in_token(prepare_database):
    """Challenge: Validly signed RS256 token referencing a non-existent user UUID."""
    ghost_user_id = uuid.uuid4()
    ghost_tenant_id = uuid.uuid4()

    ghost_token = create_access_token(user_id=ghost_user_id, tenant_id=ghost_tenant_id, role="ADMIN")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {ghost_token}"})
        assert me_res.status_code == 401, f"Expected 401 for non-existent user, got {me_res.status_code}"
        assert "Could not validate credentials" in me_res.json().get("detail", "")


@pytest.mark.asyncio
async def test_invalid_and_malformed_sub_claims(prepare_database):
    """Challenge: Validly signed RS256 tokens with non-UUID or missing sub claims."""
    now = datetime.now(timezone.utc)

    # 1. Missing sub claim
    no_sub_token = jwt.encode(
        {"tenant_id": str(uuid.uuid4()), "role": "ADMIN", "exp": int((now + timedelta(hours=1)).timestamp()), "type": "access"},
        _get_private_key(),
        algorithm="RS256",
    )

    # 2. Non-UUID sub claim
    bad_uuid_token = jwt.encode(
        {"sub": "invalid-non-uuid-string", "tenant_id": str(uuid.uuid4()), "role": "ADMIN", "exp": int((now + timedelta(hours=1)).timestamp()), "type": "access"},
        _get_private_key(),
        algorithm="RS256",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res1 = await client.get("/users/me", headers={"Authorization": f"Bearer {no_sub_token}"})
        assert res1.status_code == 401

        res2 = await client.get("/users/me", headers={"Authorization": f"Bearer {bad_uuid_token}"})
        assert res2.status_code == 401


@pytest.mark.asyncio
async def test_deactivated_user_rejected_on_users_me(prepare_database):
    """Challenge: Validly signed token for a deactivated user (is_active=False).
    
    Expected: HTTP 403 Forbidden with 'User account is deactivated'.
    """
    SessionLocal = prepare_database
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with SessionLocal() as session:
        tenant = Tenant(id=tenant_id, name="Deactivated Test Bank")
        user = User(
            id=user_id,
            email="deactivated_user@testbank.com",
            hashed_password=hash_password("Pass123456!"),
            tenant_id=tenant_id,
            role=RoleEnum.ADMIN,
            is_active=False,
        )
        session.add_all([tenant, user])
        await session.commit()

    token = create_access_token(user_id=user_id, tenant_id=tenant_id, role="ADMIN")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        me_res = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 403, f"Expected 403 for deactivated user, got {me_res.status_code}"
        assert "deactivated" in me_res.json().get("detail", "")


# ==============================================================================
# 3. MULTI-TENANCY ISOLATION & PERSISTENCE
# ==============================================================================

@pytest.mark.asyncio
async def test_multi_tenant_settings_isolation_and_independence(prepare_database):
    """Challenge: Two distinct tenants register, and Tenant A modifies settings.
    
    Expected:
    - Tenant A's settings update does NOT affect Tenant B's settings.
    - Each tenant has an isolated TenantSettings row in the database.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register Tenant A
        res_a = await client.post(
            "/auth/register",
            json={"email": "admin@tenant-a.com", "password": "Password123!", "tenant_name": "Tenant A Financial"},
        )
        assert res_a.status_code == 200
        token_a = res_a.json()["access_token"]

        # Register Tenant B
        res_b = await client.post(
            "/auth/register",
            json={"email": "admin@tenant-b.com", "password": "Password123!", "tenant_name": "Tenant B Financial"},
        )
        assert res_b.status_code == 200
        token_b = res_b.json()["access_token"]

        # Tenant A fetches settings (default)
        settings_a_res = await client.get("/settings", headers={"Authorization": f"Bearer {token_a}"})
        assert settings_a_res.status_code == 200
        settings_a = settings_a_res.json()
        assert settings_a["strict_zero_trust"] is True
        assert settings_a["gini_tolerance"] == 0.05

        # Tenant B fetches settings (default)
        settings_b_res = await client.get("/settings", headers={"Authorization": f"Bearer {token_b}"})
        assert settings_b_res.status_code == 200
        settings_b = settings_b_res.json()
        assert settings_b["strict_zero_trust"] is True
        assert settings_b["gini_tolerance"] == 0.05

        assert settings_a["tenant_id"] != settings_b["tenant_id"]
        assert settings_a["id"] != settings_b["id"]

        # Tenant A mutates settings: strict_zero_trust = False, gini_tolerance = 0.15
        update_a_res = await client.put(
            "/settings",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"strict_zero_trust": False, "gini_tolerance": 0.15},
        )
        assert update_a_res.status_code == 200
        updated_a = update_a_res.json()
        assert updated_a["strict_zero_trust"] is False
        assert updated_a["gini_tolerance"] == 0.15

        # Tenant B queries settings again: MUST BE UNCHANGED
        check_b_res = await client.get("/settings", headers={"Authorization": f"Bearer {token_b}"})
        assert check_b_res.status_code == 200
        check_b = check_b_res.json()
        assert check_b["strict_zero_trust"] is True, "Tenant B strict_zero_trust was corrupted by Tenant A"
        assert check_b["gini_tolerance"] == 0.05, "Tenant B gini_tolerance was corrupted by Tenant A"


@pytest.mark.asyncio
async def test_cross_tenant_dashboard_metrics_isolation(prepare_database):
    """Challenge: Verify that dashboard metrics queries strictly filter by tenant_id."""
    SessionLocal = prepare_database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Register Tenant Alpha
        res_alpha = await client.post(
            "/auth/register",
            json={"email": "analyst@alpha.com", "password": "Password123!", "tenant_name": "Alpha Bank"},
        )
        token_alpha = res_alpha.json()["access_token"]
        payload_alpha = decode_token(token_alpha)
        tenant_alpha_id = uuid.UUID(payload_alpha["tenant_id"])
        user_alpha_id = uuid.UUID(payload_alpha["sub"])

        # Register Tenant Beta
        res_beta = await client.post(
            "/auth/register",
            json={"email": "analyst@beta.com", "password": "Password123!", "tenant_name": "Beta Bank"},
        )
        token_beta = res_beta.json()["access_token"]

        # Insert 3 models belonging to Tenant Alpha
        async with SessionLocal() as session:
            for i in range(3):
                m = Model(
                    id=uuid.uuid4(),
                    tenant_id=tenant_alpha_id,
                    user_id=user_alpha_id,
                    name=f"Alpha Model {i}",
                    type=ModelTypeEnum.PD,
                    status=ModelStatusEnum.BREACH if i == 0 else ModelStatusEnum.PASS,
                )
                session.add(m)
            await session.commit()

        # Tenant Alpha metrics: active_models = 3, compliance_issues = 1
        metrics_alpha_res = await client.get("/dashboard/metrics", headers={"Authorization": f"Bearer {token_alpha}"})
        assert metrics_alpha_res.status_code == 200
        m_alpha = metrics_alpha_res.json()
        assert m_alpha["active_models"] == 3
        assert m_alpha["compliance_issues"] == 1

        # Tenant Beta metrics: MUST BE ZERO
        metrics_beta_res = await client.get("/dashboard/metrics", headers={"Authorization": f"Bearer {token_beta}"})
        assert metrics_beta_res.status_code == 200
        m_beta = metrics_beta_res.json()
        assert m_beta["active_models"] == 0, f"Cross-tenant leak! Tenant Beta saw {m_beta['active_models']} models"
        assert m_beta["compliance_issues"] == 0, f"Cross-tenant leak! Tenant Beta saw {m_beta['compliance_issues']} issues"


# ==============================================================================
# 4. DATABASE PERSISTENCE & INTEGRITY
# ==============================================================================

@pytest.mark.asyncio
async def test_database_persistence_across_isolated_sessions(prepare_database):
    """Challenge: Ensure records are committed to the DB and queryable across isolated sessions."""
    SessionLocal = prepare_database
    test_email = "db_persistence@example.com"
    test_password = "ComplexPassword789!"
    tenant_name = "DB Persistence Bank"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/auth/register",
            json={"email": test_email, "password": test_password, "tenant_name": tenant_name},
        )
        assert res.status_code == 200
        access_token = res.json()["access_token"]

    # Open a completely fresh DB session
    async with SessionLocal() as fresh_session:
        user_res = await fresh_session.execute(select(User).where(User.email == test_email))
        user = user_res.scalar_one_or_none()
        assert user is not None, "User not found in fresh database session"
        assert user.email == test_email
        assert user.role == RoleEnum.ADMIN
        assert user.is_active is True

        # Verify password hash cannot be reversed directly and validates with verify_password
        assert user.hashed_password != test_password, "Plaintext password stored in DB!"
        assert verify_password(test_password, user.hashed_password) is True
        assert verify_password("WrongPassword123!", user.hashed_password) is False

        # Tenant verification
        tenant_res = await fresh_session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        tenant = tenant_res.scalar_one_or_none()
        assert tenant is not None, "Tenant not found in fresh database session"
        assert tenant.name == tenant_name

        # TenantSettings verification
        settings_res = await fresh_session.execute(select(TenantSettings).where(TenantSettings.tenant_id == user.tenant_id))
        settings_row = settings_res.scalar_one_or_none()
        assert settings_row is not None, "TenantSettings not found in fresh database session"
        assert settings_row.tenant_id == user.tenant_id
        assert settings_row.strict_zero_trust is True
