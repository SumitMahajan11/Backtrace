"""Centralized Application Settings & Production Secrets Validation.

Provides strict typed settings with fail-fast validation for production environments.
In production mode, all required credentials must be explicitly provided without fallback defaults.
"""

from functools import lru_cache
from typing import Literal, Optional
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Environment mode
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    APP_NAME: str = "Backtrace"
    API_PREFIX: str = "/api"
    DEBUG: bool = False

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite:///./backtrace.db"

    # Authentication & JWT
    JWT_SECRET_KEY: str = "development_secret_key_change_in_production_min_32_chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # GitHub OAuth
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    GITHUB_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"

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

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        """Strict fail-fast validation when ENVIRONMENT=production."""
        if self.ENVIRONMENT != "production":
            return self

        errors = []

        # 1. GitHub OAuth credentials
        if not self.GITHUB_CLIENT_ID or not self.GITHUB_CLIENT_ID.strip():
            errors.append("GITHUB_CLIENT_ID is required in production and cannot be empty")
        if not self.GITHUB_CLIENT_SECRET or not self.GITHUB_CLIENT_SECRET.strip():
            errors.append("GITHUB_CLIENT_SECRET is required in production and cannot be empty")
        if not self.GITHUB_REDIRECT_URI or "localhost" in self.GITHUB_REDIRECT_URI:
            errors.append("GITHUB_REDIRECT_URI in production cannot point to localhost")

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

        if errors:
            raise ValueError(
                "Production configuration validation failed:\n - " + "\n - ".join(errors)
            )

        return self


@lru_cache()
def get_settings() -> Settings:
    """Returns cached application settings instance."""
    return Settings()
