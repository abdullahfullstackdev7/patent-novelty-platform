"""Application settings read from environment variables or a local .env file."""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic_settings import BaseSettings, SettingsConfigDict

EMBEDDING_DIM = 384
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: str = "development"  # development | test | production
    database_url: str = "postgresql+psycopg://priorart:priorart@localhost:54329/priorart"

    # Secrets. No defaults: generate them, see .env.example.
    jwt_secret: str = ""
    fernet_key: str = ""
    fernet_old_keys: str = ""  # comma separated, kept only to decrypt and rotate

    # HTTP surface
    cors_origins: str = "http://localhost:5173"
    cookie_secure: bool = True
    trust_proxy_headers: bool = False
    max_body_bytes: int = 2_000_000
    max_upload_bytes: int = 200_000

    # Authentication
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    invite_ttl_hours: int = 72
    lockout_threshold: int = 5
    lockout_max_minutes: int = 60
    password_min_length: int = 12
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4

    # Rate limits (slowapi syntax). Authentication and LLM endpoints are stricter.
    rate_limit_default: str = "120/minute"
    rate_limit_auth: str = "10/minute"
    rate_limit_llm: str = "6/minute"

    # Models
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Search tuning (section 5, Phase 2)
    hnsw_ef_search: int = 80
    search_candidates_per_query: int = 100
    rrf_k: int = 60
    rerank_depth: int = 40
    result_limit: int = 10
    cpc_vote_depth: int = 30

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def docs_enabled(self) -> bool:
        """OpenAPI and Swagger UI are served outside production only."""
        return not self.is_production

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def fernet_keys(self) -> list[str]:
        """Primary key first, then the old keys. MultiFernet encrypts with the first."""
        old = [k.strip() for k in self.fernet_old_keys.split(",") if k.strip()]
        return [self.fernet_key, *old]

    def validate_runtime(self) -> None:
        """Fail fast on missing or weak secrets and unsafe production settings."""
        if len(self.jwt_secret) < MIN_SECRET_LENGTH:
            raise RuntimeError(
                f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if not self.fernet_key:
            raise RuntimeError(
                "FERNET_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        for key in self.fernet_keys:
            Fernet(key)  # raises ValueError on a malformed key
        if "*" in self.cors_origin_list:
            raise RuntimeError("CORS_ORIGINS must be an explicit allow-list, not '*'")
        if self.is_production and not self.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
