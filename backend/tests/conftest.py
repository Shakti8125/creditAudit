"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services.llm.circuit_breaker import reset_shared_breakers


@pytest.fixture(autouse=True)
def fresh_shared_breakers():
    """Circuit breakers are process-wide (PR-01), so give every test a clean registry.

    Without this, a test that makes a provider fail would leave a breaker open for the
    tests that run after it.
    """
    reset_shared_breakers()
    yield
    reset_shared_breakers()


@pytest.fixture(autouse=True)
def default_models(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Pin every model and routing setting to its built-in default for every test.

    A developer's backend/.env or environment may override model IDs (that is the point of
    the settings), and the suite must not depend on it. A test that wants another value
    monkeypatches the setting itself. Returns the defaults object.
    """
    from app.config import settings

    defaults = Settings.model_construct()
    for name in (
        "nvidia_generation_model",
        "nvidia_fallback_generation_model",
        "nvidia_embedding_model",
        "embedding_dimensions",
        "embedding_send_dimensions",
        "nvidia_rerank_model",
        "nvidia_rerank_url",
        "nvidia_rerank_candidates",
        "gemini_generation_model",
        "gemini_generation_candidates",
        "gemini_thinking_level",
        "llm_latency_routing",
        "rerank_llm_fallback",
        "llm_breaker_failures",
        "llm_breaker_reset_seconds",
        "rerank_breaker_failures",
        "rerank_breaker_reset_seconds",
        "llm_startup_probe",
        "llm_startup_probe_timeout_seconds",
    ):
        monkeypatch.setattr(settings, name, getattr(defaults, name))
    return defaults
