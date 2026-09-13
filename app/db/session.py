"""Database engine and session management (SQLAlchemy ORM)."""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./storage.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base declarative class for all database models."""
    pass


def init_db(target_engine=engine) -> None:
    """Creates tables if they do not exist."""
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
