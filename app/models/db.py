"""SQLAlchemy ORM database models for Layer 9 storage."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
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

    # Relationship to IngestionResultModel
    ingestion_result = relationship(
        "IngestionResultModel",
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
