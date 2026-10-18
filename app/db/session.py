"""Database engine and session management (SQLAlchemy ORM)."""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

def _get_initial_database_url() -> str:
    env_name = os.getenv("ENVIRONMENT", "")
    if env_name in ("test", "testing") or "PYTEST_CURRENT_TEST" in os.environ:
        return os.getenv("DATABASE_URL", "sqlite:///:memory:")

    env_url = os.getenv("DATABASE_URL")
    url = env_url
    if not url:
        try:
            from app.core.config import get_settings
            url = get_settings().DATABASE_URL
        except Exception:
            url = "sqlite:///./app.db"

    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    if url.startswith("sqlite:////data/") and not os.path.exists("/data"):
        return "sqlite:///./app.db"
    return url

DATABASE_URL = _get_initial_database_url()


if DATABASE_URL.startswith("postgresql"):
    engine = create_engine(
        DATABASE_URL,
        pool_size=int(os.getenv("DB_POOL_SIZE", "20")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
        pool_timeout=float(os.getenv("DB_POOL_TIMEOUT", "30.0")),
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "1800")),
        pool_pre_ping=True,
        echo=False,
    )
else:
    connect_args = {"check_same_thread": False, "timeout": 30.0} if DATABASE_URL.startswith("sqlite") else {}
    if DATABASE_URL == "sqlite:///:memory:":
        from sqlalchemy.pool import StaticPool
        engine = create_engine(
            DATABASE_URL,
            connect_args=connect_args,
            poolclass=StaticPool,
            echo=False,
        )
    else:
        engine = create_engine(
            DATABASE_URL,
            connect_args=connect_args,
            echo=False,
        )

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base declarative class for all database models."""
    pass


def init_db(target_engine=engine) -> None:
    """Creates tables if they do not exist."""
    import app.models.db  # noqa: F401 - ensure models are registered
    Base.metadata.create_all(bind=target_engine)


@contextmanager
def get_db_session(target_sessionmaker=SessionLocal) -> Generator[Session, None, None]:
    """Context manager producing thread-safe database session."""
    session = target_sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
