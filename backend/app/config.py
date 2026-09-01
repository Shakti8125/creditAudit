from __future__ import annotations

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
    allowed_origins: str = "http://localhost:5173,http://localhost:3000"
    rate_limit_enabled: bool = True

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
