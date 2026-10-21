from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    yield TestingSessionLocal, engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    TestingSessionLocal, _ = test_db

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_login_page_headline_and_showcase_link(client):
    """(a) GET /login contains 'Understand any codebase' and '/showcase'."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "Understand any codebase" in response.text
    assert "/showcase" in response.text


def test_login_page_forbidden_terms_removed(client):
    """(b) GET /login does NOT contain 'Repository Archaeology' or 'Zero-Persistence'."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "Repository Archaeology" not in response.text
    assert "Zero-Persistence" not in response.text


def test_showcase_empty_state_coming_soon(client):
    """(c) GET /showcase with no showcase jobs returns 200 and contains 'coming soon'."""
    response = client.get("/showcase")
    assert response.status_code == 200
    assert "coming soon" in response.text.lower()
    assert "/login" in response.text
