"""SQLAlchemy ORM database models for Layer 9 storage."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def utc_now() -> datetime:
    """Returns current UTC timestamp without tzinfo for DB compatibility."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RepoModel(Base):
    """Database model for registered GitHub repositories and cache status."""
    __tablename__ = "repos"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    github_url: str = Column(String(255), nullable=False, index=True)
    commit_hash: str = Column(String(64), nullable=False, index=True)
    status: str = Column(String(32), nullable=False, default="pending")  # pending, processing, complete, failed
    error_message: Optional[str] = Column(Text, nullable=True)
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)
    expires_at: datetime = Column(DateTime, nullable=False, index=True)

    # Retention & Consent Data Model (Stage 6 Layer 9)
    keep_longer: bool = Column(Boolean, nullable=False, default=False)
    consent_prompt_improvement: bool = Column(Boolean, nullable=False, default=False)
    consent_future_training: bool = Column(Boolean, nullable=False, default=False)

    # Relationships
    ingestion_result = relationship(
        "IngestionResultModel",
        back_populates="repo",
        uselist=False,
        cascade="all, delete-orphan",
    )
    analysis_result = relationship(
        "AnalysisResultModel",
        back_populates="repo",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_repo_url_commit", "github_url", "commit_hash"),
    )


class IngestionResultModel(Base):
    """Database model for ingested repository output payload."""
    __tablename__ = "ingestion_results"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    repo_id: int = Column(Integer, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, unique=True)
    file_tree_json: str = Column(Text, nullable=False)
    file_contents_json: str = Column(Text, nullable=False)
    skipped_files_json: str = Column(Text, nullable=False)
    redaction_count: int = Column(Integer, nullable=False, default=0)
    clone_duration_ms: int = Column(Integer, nullable=False, default=0)
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)

    repo = relationship("RepoModel", back_populates="ingestion_result")


class AnalysisResultModel(Base):
    """Database model for full reverse-engineered analysis output payload."""
    __tablename__ = "analysis_results"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    repo_id: int = Column(Integer, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, unique=True)
    pipeline_result_json: str = Column(Text, nullable=False)
    execution_time_seconds: float = Column(Float, nullable=False, default=0.0)
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)

    repo = relationship("RepoModel", back_populates="analysis_result")


class UserModel(Base):
    """Database model for registered users authenticated via GitHub OAuth."""
    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    github_id: int = Column(Integer, nullable=False, unique=True, index=True)
    github_username: str = Column(String(100), nullable=False)
    email: Optional[str] = Column(String(255), nullable=True, index=True)
    avatar_url: Optional[str] = Column(String(500), nullable=True)
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)
    is_admin: bool = Column(Boolean, nullable=False, default=False)

    # Relationships
    refresh_tokens = relationship(
        "RefreshTokenModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    subscription = relationship(
        "SubscriptionModel",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    usage_events = relationship(
        "UsageEventModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    analysis_jobs = relationship(
        "AnalysisJobModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class RefreshTokenModel(Base):
    """Database model for server-side revocable refresh tokens (stored as SHA-256 hash)."""
    __tablename__ = "refresh_tokens"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: str = Column(String(64), nullable=False, index=True)
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)
    expires_at: datetime = Column(DateTime, nullable=False, index=True)
    revoked_at: Optional[datetime] = Column(DateTime, nullable=True)

    user = relationship("UserModel", back_populates="refresh_tokens")


class SubscriptionModel(Base):
    """Database model tracking Stripe customer and subscription lifecycle."""
    __tablename__ = "subscriptions"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    stripe_customer_id: str = Column(String(255), nullable=False, index=True)
    stripe_subscription_id: Optional[str] = Column(String(255), nullable=True, index=True)
    status: str = Column(String(64), nullable=False, default="inactive")  # active, trialing, past_due, canceled, inactive
    current_period_end: Optional[datetime] = Column(DateTime, nullable=True)
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    user = relationship("UserModel", back_populates="subscription")


class UsageEventModel(Base):
    """Immutable audit log for billing quota calculation and usage analysis."""
    __tablename__ = "usage_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: str = Column(String(64), nullable=False, default="repo_analysis")
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now, index=True)

    user = relationship("UserModel", back_populates="usage_events")


class ProcessedWebhookEventModel(Base):
    """Deduplication registry ensuring exactly-once processing of incoming Stripe webhooks."""
    __tablename__ = "processed_webhook_events"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    event_id: str = Column(String(255), unique=True, nullable=False, index=True)
    event_type: str = Column(String(100), nullable=False)
    processed_at: datetime = Column(DateTime, nullable=False, default=utc_now)


class AnalysisJobModel(Base):
    """Database model tracking user-submitted analysis jobs, progress, and results."""
    __tablename__ = "analysis_jobs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)
    user_id: int = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    repo_name: str = Column(String(255), nullable=False, index=True)
    github_url: str = Column(String(255), nullable=False)
    status: str = Column(String(32), nullable=False, default="pending")  # pending, processing, complete, failed
    run_id: str = Column(String(64), nullable=False, index=True)
    error_message: Optional[str] = Column(Text, nullable=True)
    execution_time_seconds: float = Column(Float, nullable=False, default=0.0)
    markdown_output: str = Column(Text, nullable=False, default="")
    graph_output_json: str = Column(Text, nullable=False, default="{}")
    quiz_output_json: str = Column(Text, nullable=False, default="{}")
    created_at: datetime = Column(DateTime, nullable=False, default=utc_now)
    updated_at: datetime = Column(DateTime, nullable=False, default=utc_now, onupdate=utc_now)

    user = relationship("UserModel", back_populates="analysis_jobs")

    @property
    def repo_url(self) -> str:
        return self.github_url

    @repo_url.setter
    def repo_url(self, val: str):
        self.github_url = val

    @property
    def report_markdown(self) -> str:
        return self.markdown_output

    @report_markdown.setter
    def report_markdown(self, val: str):
        self.markdown_output = val

    @property
    def graph_data(self) -> Any:
        try:
            import json
            return json.loads(self.graph_output_json) if self.graph_output_json else {}
        except Exception:
            return {}

    @property
    def quiz_data(self) -> Any:
        try:
            import json
            return json.loads(self.quiz_output_json) if self.quiz_output_json else {}
        except Exception:
            return {}




