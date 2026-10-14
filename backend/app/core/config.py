"""Application settings. Validated once at startup; invalid configuration fails fast."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AIMode = Literal["LOCAL", "HYBRID", "CLOUD"]

_INSECURE_DEFAULTS = {"change-me", "changeme", "secret", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://threadline:threadline@localhost:5436/threadline"
    redis_url: str = "redis://localhost:6382/0"
    data_dir: str = "./var"

    # Secrets. SECRET_KEY signs nothing client-visible (sessions are opaque random tokens) but is
    # used to derive the CSRF HMAC. ENCRYPTION_KEY is a Fernet key for stored connector credentials.
    secret_key: str = Field(default="dev-only-secret-key-not-for-production-use-000")
    encryption_key: str = Field(default="")

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    cookie_secure: bool = False
    session_ttl_hours: int = 24 * 7
    allow_registration: bool = True
    demo_login_enabled: bool = False  # one-click sign-in to the synthetic demo account (enable for local exploration / public demos)
    rate_limit_per_minute: int = 240
    auth_rate_limit_per_minute: int = 10  # login/register attempts per client per minute
    max_upload_mb: int = 25
    # Folders the local-files connector may index. Empty = any folder (single-user local mode only);
    # production refuses local-folder imports unless roots are configured.
    local_import_roots: Annotated[list[str], NoDecode] = []

    # Events: when true, domain events are processed in-process right after commit (tests, CLI,
    # single-process mode). When false, they are dispatched to Celery workers.
    events_eager: bool = True

    # AI defaults (users can override per account in Settings).
    default_ai_mode: AIMode = "LOCAL"
    ollama_base_url: str = "http://localhost:11434"
    reasoning_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    extraction_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    llm_extraction_enabled: bool = False  # rules always run; LLM extraction is opt-in (slow on CPU)
    llm_timeout_seconds: float = 120.0
    ollama_schema_mode: Literal["json", "grammar"] = "json"

    embedding_provider: Literal["fastembed", "hashing", "ollama"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_cache_dir: str = "./var/models"

    # Optional cloud provider (OpenAI-compatible). Never used in LOCAL mode.
    cloud_base_url: str = ""
    cloud_api_key: str = ""
    cloud_model: str = ""
    cloud_input_cost_per_mtok: float = 0.0
    cloud_output_cost_per_mtok: float = 0.0

    # Google OAuth for the Gmail/Calendar connectors (optional).
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:3000/integrations/google/callback"

    telemetry_enabled: bool = False  # nothing is ever transmitted; reserved, documented as opt-in
    otel_exporter_endpoint: str = ""

    @field_validator("cors_origins", "local_import_roots", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _check_production(self) -> Settings:
        if self.environment == "production":
            if self.secret_key in _INSECURE_DEFAULTS or self.secret_key.startswith("dev-only"):
                raise ValueError("SECRET_KEY must be set to a strong random value in production")
            if not self.encryption_key:
                raise ValueError("ENCRYPTION_KEY must be set in production")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production")
        if self.embedding_dim != 384:
            raise ValueError("The schema stores 384-dimension vectors; EMBEDDING_DIM must be 384")
        return self

    @property
    def cloud_configured(self) -> bool:
        return bool(self.cloud_base_url and self.cloud_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
