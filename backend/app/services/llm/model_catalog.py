"""Which provider models the app calls and which ones the probes check (PR-01, QA-006).

Every ID is a setting in ``app/config.py`` (environment-overridable). This module only
reads them, so the app, the start-up probe and ``scripts/diag/pr00_probe.py`` cannot
drift apart: the probe checks the configured ID first and then the configured
candidates. Model churn is frequent, so nothing here is a constant to edit in code:
change the environment, then run ``scripts/demo.sh preflight``.

PR-01b replaces these single settings with role-based chains; the helpers below are the
seam it will replace.
"""

from __future__ import annotations

from app.config import Settings
from app.config import settings as app_settings

NVIDIA_RERANK_URL_TEMPLATE = "https://ai.api.nvidia.com/v1/retrieval/{model}/reranking"


def split_ids(raw: str) -> tuple[str, ...]:
    """Split a comma-separated list of model IDs, dropping blanks and duplicates."""
    seen: dict[str, None] = {}
    for part in raw.split(","):
        part = part.strip()
        if part:
            seen.setdefault(part, None)
    return tuple(seen)


def _first_then(active: str, candidates: str) -> tuple[str, ...]:
    """Return the active ID first, then the candidates, without duplicates."""
    return split_ids(f"{active},{candidates}")


def nvidia_generation_models(cfg: Settings | None = None) -> tuple[str, ...]:
    """NVIDIA chat models in the order they are tried: the primary, then the 404 fallback."""
    cfg = cfg or app_settings
    return split_ids(f"{cfg.nvidia_generation_model},{cfg.nvidia_fallback_generation_model}")


def nvidia_rerank_candidates(cfg: Settings | None = None) -> tuple[str, ...]:
    """Reranker IDs to check: the configured one first, then ``NVIDIA_RERANK_CANDIDATES``."""
    cfg = cfg or app_settings
    return _first_then(cfg.nvidia_rerank_model, cfg.nvidia_rerank_candidates)


def gemini_generation_candidates(cfg: Settings | None = None) -> tuple[str, ...]:
    """Gemini chat IDs to check: the configured one first, then ``GEMINI_GENERATION_CANDIDATES``."""
    cfg = cfg or app_settings
    return _first_then(cfg.gemini_generation_model, cfg.gemini_generation_candidates)


def rerank_url(model: str | None = None, cfg: Settings | None = None) -> str:
    """Return the rerank endpoint for ``model`` (default: the configured reranker).

    ``NVIDIA_RERANK_URL`` overrides the endpoint of the configured model only. Any other
    model, such as a probe candidate, uses the standard model-in-path template.
    """
    cfg = cfg or app_settings
    model = model or cfg.nvidia_rerank_model
    if model == cfg.nvidia_rerank_model and cfg.nvidia_rerank_url.strip():
        return cfg.nvidia_rerank_url.strip()
    return NVIDIA_RERANK_URL_TEMPLATE.format(model=model)
