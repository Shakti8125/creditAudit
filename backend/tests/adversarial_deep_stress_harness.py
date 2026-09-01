"""Adversarial Deep Stress Verification Harness for ModelAudit AI Backend."""
from __future__ import annotations

import asyncio
import io
import time
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import Base, get_db
from app.models.user import User, Tenant, RoleEnum
from app.models.audit import Model, ModelVersion, ModelTypeEnum, ModelStatusEnum
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.system import TenantSettings, Notification
from app.services.privacy.bank_matcher import BankNameMatcher
from app.services.privacy.ner_masker import NERMasker
from app.services.privacy.masking_pipeline import MaskingPipeline
from app.services.privacy.egress_validator import EgressValidator, EgressViolationError
from app.services.privacy.entity_registry import EntityRegistry
from app.services.chunker import MarkdownChunker
from app.services.llm.circuit_breaker import CircuitBreaker, CircuitState
from app.services.llm.router import LLMRouter, AllProvidersUnavailableError
from app.utils.security import create_access_token, hash_password

SQLALCHEMY_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    autocommit=False, autoflush=False, bind=test_engine, class_=AsyncSession, expire_on_commit=False
)

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


def test_adversarial_privacy_overlapping_and_commas():
    """Adversarially test overlapping entities, nested substrings, and complex comma financial numbers."""
    pipeline = MaskingPipeline()
    raw_text = (
        "First Abu Dhabi Bank PJSC (also known as First Abu Dhabi Bank or FAB) provided a credit facility "
        "of AED 1,250,000,000.50 ($340,500,000) to AlphaCorp International Holdings Limited (AlphaCorp). "
        "The Lead Risk Officer Dr. Johnathan Smith-Doe, Jr. signed the approval on 31 December 2023. "
        "The loan has a margin of 125.5 bps over 3-month EIBOR (3.45%), with Gini: 65.2% and KS: 39.8%. "
        "Contact compliance at compliance-risk@firstabudhabi.ae or call +971-4-123-4567. "
        "Also, the Market Standard validator was Dan Miller from Standard Chartered Bank."
    )

    masked_text, registry = pipeline.mask_document(raw_text)

    # 1. Check for token nesting/corruption
    assert "[[" not in masked_text
    assert "]]" not in masked_text

    # 2. Check that financial numbers with commas are NOT masked
    assert "1,250,000,000.50" in masked_text
    assert "340,500,000" in masked_text
    assert "125.5 bps" in masked_text
    assert "3.45%" in masked_text
    assert "65.2%" in masked_text
    assert "39.8%" in masked_text

    # 3. Check that common sub-words like 'Market' or 'Standard' in non-bank context didn't corrupt
    assert "Market Standard" in masked_text

    # 4. Check egress validation passes on masked text
    validator = EgressValidator()
    report = validator.validate(masked_text, registry)
    assert report.is_clean is True
    assert len(report.violations) == 0

    # 5. Check roundtrip unmasking is 100% lossless
    unmasked = registry.unmask_text(masked_text)
    assert unmasked == raw_text, f"Roundtrip unmasking mismatch!\nExpected:\n{raw_text}\nGot:\n{unmasked}"


def test_adversarial_markdown_tables_and_splitting():
    """Adversarially test markdown chunker on complex multi-column tables, abbreviations, and comma numbers."""
    chunker = MarkdownChunker(chunk_size=500, overlap=100)

    doc = (
        "# Model Validation Report\n\n"
        "## Executive Summary\n\n"
        "The PD model for retail credit was evaluated under CBUAE MMG standards by Dr. H. Smith, Jr. "
        "The portfolio total exposure was AED 25,750,000.00 across 12,500 facilities. "
        "e.g., small business loans represented 45.5% of exposure, i.e., AED 11,716,250.00. "
        "Overall calibration error was 0.012 (vs. benchmark 0.050).\n\n"
        "## Performance Metrics Table\n\n"
        "| Metric ID | Metric Name | Benchmark | Observed | Status | Notes |\n"
        "|---|---|---|---|---|---|\n"
        "| M-01 | Gini Coefficient | >= 0.45 | 0.64 | PASS | Excellent discrimination |\n"
        "| M-02 | KS Statistic | >= 30.0% | 38.5% | PASS | Peak separation at score 620 |\n"
        "| M-03 | Population Stability Index (PSI) | <= 0.10 | 0.04 | PASS | Insignificant population drift |\n"
        "| M-04 | Hosmer-Lemeshow p-value | >= 0.05 | 0.18 | PASS | Good calibration fit |\n"
        "| M-05 | Brier Score | <= 0.15 | 0.09 | PASS | Low quadratic error |\n\n"
        "## Conclusions\n\n"
        "The validation confirms model readiness for production deployment."
    )

    chunks = chunker.chunk(doc)

    # 1. Verify table chunk exists and is not dropped
    table_chunks = [c for c in chunks if "| Metric ID |" in c]
    assert len(table_chunks) >= 1, "Table chunk was missing!"

    # 2. Check all table rows are preserved
    for metric in ["M-01", "M-02", "M-03", "M-04", "M-05"]:
        assert any(metric in c for c in chunks), f"Metric {metric} missing from chunks!"

    # 3. Check comma numbers and abbreviations are preserved intact
    all_chunks_text = "\n".join(chunks)
    assert "25,750,000.00" in all_chunks_text
    assert "11,716,250.00" in all_chunks_text
    assert "Dr. H. Smith, Jr." in all_chunks_text or "Dr. H. Smith" in all_chunks_text


@pytest.mark.asyncio
async def test_adversarial_circuit_breaker_high_concurrency():
    """Adversarially test CircuitBreaker under high concurrency and state transitions."""
    cb = CircuitBreaker("adversarial_test", max_failures=5, reset_timeout=1)

    # 1. Run 50 concurrent successful calls
    async def fast_success(i: int) -> int:
        await asyncio.sleep(0.005)
        return i * 2

    success_tasks = [cb.call(fast_success, i) for i in range(50)]
    success_results = await asyncio.gather(*success_tasks)
    assert success_results == [i * 2 for i in range(50)]
    assert cb.get_state() == CircuitState.CLOSED
    assert cb.failures == 0

    # 2. Trigger 5 failures concurrently to trip circuit
    async def failing_call(i: int):
        await asyncio.sleep(0.005)
        raise ConnectionResetError(f"Connection reset {i}")

    fail_tasks = [cb.call(failing_call, i) for i in range(5)]
    results = await asyncio.gather(*fail_tasks, return_exceptions=True)
    assert all(isinstance(r, ConnectionResetError) for r in results)
    assert cb.get_state() == CircuitState.OPEN

    # 3. Verify fast-fail on 20 concurrent calls while OPEN
    async def blocked_call():
        return "should not run"

    blocked_tasks = [cb.call(blocked_call) for _ in range(20)]
    blocked_results = await asyncio.gather(*blocked_tasks, return_exceptions=True)
    assert all(isinstance(r, RuntimeError) and "OPEN" in str(r) for r in blocked_results)

    # 4. Wait for reset timeout -> HALF_OPEN
    await asyncio.sleep(1.05)
    assert cb.get_state() == CircuitState.HALF_OPEN

    # 5. Concurrent probes restore to CLOSED
    probe_tasks = [cb.call(fast_success, 10) for _ in range(10)]
    probe_results = await asyncio.gather(*probe_tasks)
    assert probe_results == [20] * 10
    assert cb.get_state() == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_adversarial_streaming_failover():
    """Adversarially test streaming router failover behavior before and during streaming."""
    mock_nvidia = MagicMock()
    mock_gemini = MagicMock()

    # Scenario A: Nvidia fails on initialization -> seamless failover to Gemini
    async def failing_nvidia_stream(*args, **kwargs):
        raise ConnectionError("Nvidia NIM gateway timeout")
        yield  # make it a generator

    async def fallback_gemini_stream(*args, **kwargs):
        for token in ["Gemini ", "fallback ", "stream ", "active."]:
            await asyncio.sleep(0.001)
            yield token

    mock_nvidia.generate_stream = failing_nvidia_stream
    mock_gemini.generate_stream = fallback_gemini_stream

    router = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)

    collected_chunks = []
    async for chunk in router.generate_stream("Stream test prompt"):
        collected_chunks.append(chunk)

    assert collected_chunks == ["Gemini ", "fallback ", "stream ", "active."]

    # Scenario B: Mid-stream failure must raise exception without re-yielding corrupted headers
    async def mid_stream_failing(*args, **kwargs):
        yield "Initial chunk 1"
        yield "Initial chunk 2"
        raise IOError("Socket aborted mid-stream")

    mock_gemini.generate_stream = mid_stream_failing
    router_b = LLMRouter(nvidia=mock_nvidia, gemini=mock_gemini)
    # Force gemini as primary
    router_b.circuit_breakers["nvidia"].state = CircuitState.OPEN

    yielded = []
    with pytest.raises(IOError, match="Socket aborted mid-stream"):
        async for chunk in router_b.generate_stream("Prompt"):
            yielded.append(chunk)

    assert yielded == ["Initial chunk 1", "Initial chunk 2"]


@pytest.mark.asyncio
async def test_adversarial_multitenancy_isolation_e2e():
    """Adversarially test cross-tenant access prevention across models, dashboard, and settings."""
    app.dependency_overrides[get_db] = override_get_db
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    t1_id = uuid.uuid4()
    t2_id = uuid.uuid4()
    u1_id = uuid.uuid4()
    u2_id = uuid.uuid4()
    m1_id = uuid.uuid4()
    m2_id = uuid.uuid4()
    v1_id = uuid.uuid4()
    v2_id = uuid.uuid4()

    async with TestingSessionLocal() as session:
        t1 = Tenant(id=t1_id, name="Bank One")
        t2 = Tenant(id=t2_id, name="Bank Two")
        u1 = User(
            id=u1_id, email="auditor@bankone.ae",
            hashed_password=hash_password("Pass123!"),
            tenant_id=t1_id, role=RoleEnum.ANALYST, is_active=True
        )
        u2 = User(
            id=u2_id, email="auditor@banktwo.ae",
            hashed_password=hash_password("Pass123!"),
            tenant_id=t2_id, role=RoleEnum.ANALYST, is_active=True
        )
        m1 = Model(
            id=m1_id, tenant_id=t1_id, user_id=u1_id,
            name="Bank One Wholesale Rating Model",
            type=ModelTypeEnum.PD, status=ModelStatusEnum.PASS
        )
        m2 = Model(
            id=m2_id, tenant_id=t2_id, user_id=u2_id,
            name="Bank Two Secret Retail Scorecard",
            type=ModelTypeEnum.CREDIT_SCORING, status=ModelStatusEnum.BREACH
        )
        v1 = ModelVersion(id=v1_id, model_id=m1_id, version="1.0.0", is_current=True)
        v2 = ModelVersion(id=v2_id, model_id=m2_id, version="2.0.0", is_current=True)

        s1 = TenantSettings(tenant_id=t1_id, gini_tolerance=0.05)
        s2 = TenantSettings(tenant_id=t2_id, gini_tolerance=0.10)

        n1 = Notification(tenant_id=t1_id, user_id=u1_id, title="Bank One Alert", description="Model passed")
        n2 = Notification(tenant_id=t2_id, user_id=u2_id, title="Bank Two Secret Alert", description="Breach occurred")

        session.add_all([t1, t2, u1, u2, m1, m2, v1, v2, s1, s2, n1, n2])
        await session.commit()

    token_t1 = create_access_token(user_id=u1_id, tenant_id=t1_id, role="ANALYST")
    token_t2 = create_access_token(user_id=u2_id, tenant_id=t2_id, role="ANALYST")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Tenant 1 lists models -> should ONLY see Bank One model
        res = await client.get("/models", headers={"Authorization": f"Bearer {token_t1}"})
        assert res.status_code == 200
        models_t1 = res.json()
        assert len(models_t1) == 1
        assert models_t1[0]["id"] == str(m1_id)
        assert "Bank Two" not in str(models_t1)

        # 2. Tenant 1 attempts to fetch Tenant 2's specific model -> 404
        res_m2 = await client.get(f"/models/{m2_id}", headers={"Authorization": f"Bearer {token_t1}"})
        assert res_m2.status_code == 404

        # 3. Tenant 1 attempts to fetch Tenant 2's model versions -> 404
        res_v2 = await client.get(f"/models/{m2_id}/versions", headers={"Authorization": f"Bearer {token_t1}"})
        assert res_v2.status_code == 404

        # 4. Tenant 1 attempts to export Tenant 2's model data -> 404
        res_exp2 = await client.get(f"/models/{m2_id}/export-data", headers={"Authorization": f"Bearer {token_t1}"})
        assert res_exp2.status_code == 404

        # 5. Tenant 1 checks dashboard metrics -> should reflect only Tenant 1 stats
        res_dash = await client.get("/dashboard/metrics", headers={"Authorization": f"Bearer {token_t1}"})
        assert res_dash.status_code == 200
        dash_data = res_dash.json()
        assert dash_data["active_models"] == 1
        assert dash_data["compliance_issues"] == 0  # m1 has PASS status; m2 (BREACH) is in Tenant 2!

        # 6. Tenant 1 gets notifications -> should ONLY see Tenant 1 alert
        res_notif = await client.get("/notifications", headers={"Authorization": f"Bearer {token_t1}"})
        assert res_notif.status_code == 200
        notifs = res_notif.json()
        assert len(notifs) == 1
        assert notifs[0]["title"] == "Bank One Alert"
        assert "Bank Two" not in str(notifs)

        # 7. Tenant 1 global search for 'Bank Two' -> should return 0 models
        res_search = await client.get("/search?q=Bank Two", headers={"Authorization": f"Bearer {token_t1}"})
        assert res_search.status_code == 200
        search_items = res_search.json()["results"]
        model_results = [item for item in search_items if item["type"] == "model"]
        assert len(model_results) == 0, f"Tenant 1 search leaked Tenant 2 models: {model_results}"

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.pop(get_db, None)
