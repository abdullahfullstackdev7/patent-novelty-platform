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
    rate_limit_contact: str = "5/hour"

    # LLM gateway (Phase 4). Keys are optional: a provider without a key is simply unavailable.
    groq_api_key: str = ""
    gemini_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-20b"
    gemini_model: str = "gemini-3.1-flash-lite"  # env GEMINI_MODEL, never the 2.5 family
    gemini_thinking_level: str = "minimal"  # empty string omits the thinking config
    llm_mode: str = "auto"  # auto | groq | gemini | local_only (global default)
    llm_timeout_seconds: float = 30.0
    llm_max_request_tokens: int = 3500  # Groq free plan: 8K tokens per minute is the binding cap
    llm_retry_attempts: int = 2  # attempts per provider before failing over
    llm_retry_max_wait_seconds: float = 8.0  # longer retry-after values fail over immediately
    llm_max_bucket_wait_seconds: float = 12.0  # wait for the token bucket at most this long
    llm_breaker_failures: int = 3
    llm_breaker_open_seconds: float = 60.0
    # Free-tier limits. Gemini limits are per model and project, check aistudio.google.com.
    groq_rpm: int = 30
    groq_rpd: int = 1000
    groq_tpm: int = 8000
    groq_tpd: int = 200_000
    gemini_rpm: int = 10
    gemini_rpd: int = 250
    gemini_tpm: int | None = None
    gemini_tpd: int | None = None

    # Analysis pipeline (Phase 5)
    pipeline_references: int = 3  # references charted per case, 1 to 5
    pipeline_passages_per_element: int = 2
    pipeline_passage_words: int = 120
    pipeline_low_threshold: float = 0.35  # cosine below this: not found, no LLM
    pipeline_high_threshold: float = 0.88  # cosine above this plus keyword overlap: disclosed
    pipeline_keyword_overlap: float = 0.6
    pipeline_fallback_partial: float = 0.65  # without an LLM, cosine at or above this is partial
    job_max_attempts: int = 3
    job_poll_seconds: float = 2.0
    job_stuck_minutes: int = 15

    # Billing and analytics (Phase 6). Prices are modelled reference assumptions, not quotes.
    invoice_due_days: int = 30
    token_target_per_case: int = 9000
    price_groq_in_per_mtok: float = 0.075
    price_groq_out_per_mtok: float = 0.30
    price_gemini_in_per_mtok: float = 0.10
    price_gemini_out_per_mtok: float = 0.40
    infra_cost_monthly: float = 350.0

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

    def validate_llm(self) -> None:
        if self.llm_mode not in {"auto", "groq", "gemini", "local_only"}:
            raise RuntimeError("LLM_MODE must be one of auto, groq, gemini, local_only")
        if self.gemini_model.startswith("gemini-2.5"):
            raise RuntimeError(
                "GEMINI_MODEL must not be a Gemini 2.5 model (scheduled for shutdown)"
            )

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
        self.validate_llm()


@lru_cache
def get_settings() -> Settings:
    return Settings()
