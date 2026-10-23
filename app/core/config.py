"""Centralized Application Settings & Production Secrets Validation.

Provides strict typed settings with fail-fast validation for production environments.
In production mode, all required credentials must be explicitly provided without fallback defaults.
"""

from functools import lru_cache
from typing import Any, Literal, Optional
from urllib.parse import urlsplit
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment mode
    ENVIRONMENT: Literal["development", "test", "production"] = "production"
    RETENTION_CLEANUP_ENABLED: bool = True
    APP_NAME: str = "Backtrace"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    @property
    def is_production(self) -> bool:
        """Returns True if the application is running in production mode."""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Returns True if the application is running in development mode."""
        return self.ENVIRONMENT == "development"

    @property
    def is_test(self) -> bool:
        """Returns True if the application is running in test mode."""
        return self.ENVIRONMENT == "test"

    # Database
    DATABASE_URL: str = "sqlite:///./backtrace.db"

    # Authentication & JWT
    JWT_SECRET_KEY: str = "development_secret_key_change_in_production_min_32_chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # GitHub OAuth & API Access
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/auth/github/callback"
    GITHUB_FRONTEND_REDIRECT_URI: Optional[str] = None
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_PAT: Optional[str] = None

    # Stripe Billing
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None
    STRIPE_PRICE_ID_PRO: Optional[str] = None
    STRIPE_SUCCESS_URL: str = "http://localhost:8000/dashboard?session_id={CHECKOUT_SESSION_ID}"
    STRIPE_CANCEL_URL: str = "http://localhost:8000/dashboard"
    FREE_TIER_MONTHLY_LIMIT: int = 5

    # Monitoring & Analytics
    SENTRY_DSN: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    POSTHOG_API_KEY: Optional[str] = None
    POSTHOG_HOST: str = "https://app.posthog.com"

    # Distributed Rate Limiting & Redis (Prompt 27)
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"
    RATE_LIMIT_CIRCUIT_BREAKER_THRESHOLD: int = 5
    RATE_LIMIT_REDIS_TIMEOUT: float = 0.5

    # CORS & Security
    ALLOWED_HOSTS: list[str] = ["*"]
    CORS_ORIGINS: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    # Points & Economy Engine (Prompt 23 & 24)
    POINTS_FIRST_SOLVE_ONLY: bool = True
    POINTS_BASE_VALUE: int = 50  # base points per milestone, adjustable
    POINTS_HINT_1_MULTIPLIER: float = 0.50
    POINTS_HINT_2_MULTIPLIER: float = 0.25
    POINTS_SOLUTION_REVEALED_MULTIPLIER: float = 0.0
    POINTS_MIN_REPO_FILES: int = 5
    POINTS_MIN_REPO_LOC: int = 150
    POINTS_EXPIRY_DAYS: int = 180
    POINTS_QUOTA_REWARD_COST: int = 100  # Cost in points for extra monthly quota
    POINTS_QUOTA_REWARD_AMOUNT: int = 2  # Number of repos added per quota redemption
    ENABLE_PUBLIC_LEADERBOARD: bool = True  # Feature flag for public community ranking

    # Sandbox & Execution Controls
    SANDBOX_ENABLED: Optional[bool] = None

    # Ingestion Limits
    MAX_REPO_MB: int = 200

    # LLM & Narration Settings
    LLM_PROVIDER: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_TIMEOUT: float = 120.0
    NARRATION_TIME_BUDGET_SECONDS: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def normalize_env(cls, v: str) -> str:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower in ("prod", "production"):
                return "production"
            if v_lower in ("test", "testing"):
                return "test"
            if v_lower in ("dev", "development"):
                return "development"
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="before")
    @classmethod
    def populate_redirect_uri_fallback(cls, data: Any) -> Any:
        if isinstance(data, dict):
            r_uri = data.get("GITHUB_REDIRECT_URI")
            fe_uri = data.get("GITHUB_FRONTEND_REDIRECT_URI")
            if (not r_uri or r_uri == "http://localhost:8000/auth/github/callback") and fe_uri:
                data["GITHUB_REDIRECT_URI"] = fe_uri
        return data

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        """Strict fail-fast validation when ENVIRONMENT=production."""
        if self.SANDBOX_ENABLED is None:
            # Default false in production, true in development/test
            object.__setattr__(self, "SANDBOX_ENABLED", self.ENVIRONMENT != "production")

        if self.ENVIRONMENT != "production":
            return self

        # In production, ensure DEBUG is strictly disabled
        object.__setattr__(self, "DEBUG", False)

        errors = []

        # 1. GitHub OAuth credentials
        if not self.GITHUB_CLIENT_ID or not self.GITHUB_CLIENT_ID.strip():
            errors.append("GITHUB_CLIENT_ID is required in production and cannot be empty")
        if not self.GITHUB_CLIENT_SECRET or not self.GITHUB_CLIENT_SECRET.strip():
            errors.append("GITHUB_CLIENT_SECRET is required in production and cannot be empty")
        redirect_url = (self.GITHUB_REDIRECT_URI or "").strip()
        parsed_redirect = urlsplit(redirect_url)
        redirect_host = (parsed_redirect.hostname or "").lower()
        if (
            not redirect_url
            or not redirect_host
            or redirect_host == "localhost"
            or redirect_host.endswith(".localhost")
            or redirect_host == "127.0.0.1"
        ):
            errors.append("GITHUB_REDIRECT_URI in production cannot point to localhost or 127.0.0.1")
        elif (
            redirect_host == "yourdomain.com"
            or redirect_host.endswith(".yourdomain.com")
            or redirect_host == "example.com"
            or redirect_host.endswith(".example.com")
        ):
            errors.append("GITHUB_REDIRECT_URI in production cannot point to placeholder domain (yourdomain.com, example.com)")

        # 2. JWT Configuration
        if len(self.JWT_SECRET_KEY.strip()) < 32:
            errors.append("JWT_SECRET_KEY must be at least 32 characters long in production")
        if "development_secret_key" in self.JWT_SECRET_KEY:
            errors.append("JWT_SECRET_KEY cannot use development default in production")

        # 3. Stripe Billing Credentials
        if not self.STRIPE_SECRET_KEY or not self.STRIPE_SECRET_KEY.strip():
            errors.append("STRIPE_SECRET_KEY is required in production")
        elif not (self.STRIPE_SECRET_KEY.startswith("sk_live_") or self.STRIPE_SECRET_KEY.startswith("sk_test_")):
            errors.append("STRIPE_SECRET_KEY must be a valid Stripe API key (sk_live_... or sk_test_...)")

        if not self.STRIPE_WEBHOOK_SECRET or not self.STRIPE_WEBHOOK_SECRET.strip():
            errors.append("STRIPE_WEBHOOK_SECRET is required in production")
        elif not self.STRIPE_WEBHOOK_SECRET.startswith("whsec_"):
            errors.append("STRIPE_WEBHOOK_SECRET must be a valid Stripe webhook secret (whsec_...)")

        if not self.STRIPE_PRICE_ID_PRO or not self.STRIPE_PRICE_ID_PRO.strip():
            errors.append("STRIPE_PRICE_ID_PRO is required in production")
        elif not self.STRIPE_PRICE_ID_PRO.startswith("price_"):
            errors.append("STRIPE_PRICE_ID_PRO must start with 'price_'")

        # 4. Debug check
        if self.DEBUG:
            errors.append("DEBUG mode must be disabled (False) in production")

        # 5. Database URL (Production must use a persistent PostgreSQL database, not SQLite or memory)
        db_url = (self.DATABASE_URL or "").strip().lower()
        if not db_url or db_url.startswith("sqlite") or ":memory:" in db_url:
            errors.append(
                "DATABASE_URL cannot be SQLite or memory database in production. A production PostgreSQL URL is required."
            )

        if errors:
            raise ValueError(
                "Production configuration validation failed:\n - " + "\n - ".join(errors)
            )

        return self


@lru_cache()
def get_settings() -> Settings:
    """Returns cached application settings instance."""
    return Settings()
