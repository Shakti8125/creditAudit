from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig:
    """Database configuration container."""

    def __init__(self, url: str) -> None:
        self.url = url


class RedisConfig:
    """Redis configuration container."""

    def __init__(self, url: str, token: str) -> None:
        self.url = url
        self.token = token


class PineconeConfig:
    """Pinecone vector database configuration container."""

    def __init__(self, api_key: str, index_name: str) -> None:
        self.api_key = api_key
        self.index_name = index_name


class NvidiaConfig:
    """NVIDIA NIM provider configuration container."""

    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url


class GeminiConfig:
    """Google Gemini provider configuration container."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key


class JwtConfig:
    """JWT authentication and cryptographic configuration container."""

    def __init__(
        self,
        private_key: str = "",
        public_key: str = "",
        algorithm: str = "RS256",
        secret_key: str = "",
    ) -> None:
        self.private_key = private_key
        self.public_key = public_key
        self.algorithm = algorithm
        self.secret_key = secret_key or private_key


class RateLimitConfig:
    """Rate limit configuration container."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    database_url: str = ""
    redis_url: str = ""
    redis_token: str = ""
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    gemini_api_key: str = ""
    pinecone_api_key: str = ""
    pinecone_index_name: str = ""
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    jwt_secret_key: str = ""
    jwt_algorithm: str = "RS256"
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,https://creditaudit.vercel.app"
    rate_limit_enabled: bool = True
    # RAG_TELEMETRY_ENABLED: persist per-request RAG traces (masked query only).
    rag_telemetry_enabled: bool = True
    # WARM_MODELS_ON_STARTUP: load Docling and spaCy/Presidio before serving, so the first
    # upload does not pay for them (QA-026). Off by default; the local demo turns it on.
    warm_models_on_startup: bool = False

    # --- Provider models and LLM routing (PR-01, QA-006) ---
    # Every model ID the app calls is an exact, env-overridable setting, never a constant in a
    # provider. The defaults come from public docs and were NOT confirmed by a live probe
    # (docs/qa/README.md section 5): run `scripts/demo.sh preflight` after changing any of them.
    nvidia_generation_model: str = "nvidia/nemotron-3-super-120b-a12b"
    # Tried only when the primary returns 404 (NVIDIA retires NIM functions but leaves them listed).
    nvidia_fallback_generation_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    # Embeddings are pinned: one model, one dimension, never a failover (AGENTS.md, CorpusPlan section 8).
    nvidia_embedding_model: str = "nvidia/nemotron-3-embed-1b"
    # Vector size of the Pinecone index. Vectors from the model are sliced to this size and
    # L2-renormalised when longer, and rejected when shorter. 0 turns the pin off.
    embedding_dimensions: int = Field(default=1024, ge=0)
    # Also send `dimensions` in the embeddings request. Off until the probe shows the hosted NIM accepts it.
    embedding_send_dimensions: bool = False
    # Confirmed live on 2026-10-04 (HTTP 200, the relevant passage ranked first). The text-only
    # llama-nemotron-rerank-1b-v2 reached end of life on 2026-08-25 (HTTP 410) and the older
    # llama-3.2-nv-rerankqa-1b-v2 answers 404; both stay in the candidates so the probe can show it.
    nvidia_rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2"
    # Full rerank endpoint; empty derives it from the model ID (see app/services/llm/model_catalog.py).
    nvidia_rerank_url: str = ""
    # Comma-separated reranker IDs the probe checks next to the configured one.
    nvidia_rerank_candidates: str = (
        "nvidia/llama-nemotron-rerank-vl-1b-v2,nvidia/llama-nemotron-rerank-1b-v2,nvidia/llama-3.2-nv-rerankqa-1b-v2"
    )
    # Gemini is the failover-only backup on the free tier (D4, D11); it never serves embeddings.
    gemini_generation_model: str = "gemini-3.6-flash"
    # Comma-separated Gemini IDs the probe checks next to the configured one.
    gemini_generation_candidates: str = "gemini-3.6-flash,gemini-3.5-flash,gemini-flash-latest"
    # Optional Gemini thinking level for plain chat calls (for example "low"); empty sends nothing.
    gemini_thinking_level: str = ""
    # Promote Gemini to primary when its median latency is lower. Off: NVIDIA first, Gemini on failure only.
    llm_latency_routing: bool = False
    # Score passages with Gemini when the NVIDIA reranker is down. Off: 20 slow calls per query.
    rerank_llm_fallback: bool = False
    # Circuit breakers are per (provider, method). Rerank trips sooner and stays open longer, because a
    # missing reranker only costs ranking quality and will not heal in 30 seconds.
    llm_breaker_failures: int = Field(default=5, ge=1)
    llm_breaker_reset_seconds: int = Field(default=30, ge=1)
    rerank_breaker_failures: int = Field(default=3, ge=1)
    rerank_breaker_reset_seconds: int = Field(default=300, ge=1)
    # LLM_STARTUP_PROBE: a few tiny synthetic calls in the background at start-up, logged only.
    llm_startup_probe: bool = False
    llm_startup_probe_timeout_seconds: float = Field(default=5.0, gt=0)

    # --- Structured output (PR-02, QA-005) ---
    # How the NVIDIA request asks for schema-constrained JSON. Confirmed live on 2026-10-04: the
    # hosted API answers 400 to `nvext.guided_json` and returns valid JSON for a top-level
    # `guided_json` with thinking off. The other two are the variants `scripts/diag/pr00_probe.py`
    # also tests; `scripts/demo.sh preflight` reports whether this one still works.
    nvidia_structured_mode: Literal["nvext_guided_json", "top_guided_json", "response_format_json_schema"] = (
        "top_guided_json"
    )
    # Send chat_template_kwargs.enable_thinking=false on structured calls, so reasoning tokens
    # do not eat the output budget. Set false only if preflight shows the parameter is rejected.
    nvidia_structured_disable_thinking: bool = True
    # Output-token budget of a structured call (gap analysis, compare). A call cut off at the
    # budget is retried once with double the budget, up to STRUCTURED_MAX_TOKENS_CAP.
    structured_max_tokens: int = Field(default=4096, ge=1)
    structured_max_tokens_cap: int = Field(default=8192, ge=1)
    # Gemini structured output: `auto` tries responseJsonSchema and falls back to responseSchema
    # when the model or SDK rejects it (and remembers which worked); or pin one of the two.
    gemini_structured_schema_mode: Literal["auto", "response_json_schema", "response_schema"] = "auto"
    # Optional Gemini thinking level for structured calls (for example "low"); empty sends nothing.
    gemini_structured_thinking_level: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def database(self) -> DatabaseConfig:
        return DatabaseConfig(self.database_url)

    @property
    def redis(self) -> RedisConfig:
        return RedisConfig(self.redis_url, self.redis_token)

    @property
    def pinecone(self) -> PineconeConfig:
        return PineconeConfig(self.pinecone_api_key, self.pinecone_index_name)

    @property
    def nvidia(self) -> NvidiaConfig:
        return NvidiaConfig(self.nvidia_api_key, self.nvidia_base_url)

    @property
    def gemini(self) -> GeminiConfig:
        return GeminiConfig(self.gemini_api_key)

    @property
    def jwt(self) -> JwtConfig:
        return JwtConfig(
            private_key=self.jwt_private_key,
            public_key=self.jwt_public_key,
            algorithm=self.jwt_algorithm,
            secret_key=self.jwt_secret_key,
        )

    @property
    def rate_limits(self) -> RateLimitConfig:
        return RateLimitConfig(enabled=self.rate_limit_enabled)


settings = Settings()
