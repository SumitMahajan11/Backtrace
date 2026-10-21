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


def test_privacy_page_public_and_sections(client):
    """GET /privacy returns 200 without login and contains its section titles."""
    response = client.get("/privacy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text
    assert "Last updated" in response.text
    assert "What we store" in response.text
    assert "How long" in response.text
    assert "Who processes your code" in response.text
    assert "GitHub permissions" in response.text
    assert "Deleting your data" in response.text
    assert "To delete your data, open an issue or contact support" in response.text


def test_pricing_page_public_and_sections(client):
    """GET /pricing returns 200 without login and contains its section titles."""
    response = client.get("/pricing")
    assert response.status_code == 200
    assert "Pricing" in response.text
    assert "Free Plan" in response.text
    assert "Pro Plan" in response.text
    assert "5 repository analyses" in response.text
    assert "100 MB" in response.text
    assert "Unlimited repository analyses" in response.text


def test_healthz_endpoint(client):
    """GET /healthz returns {"status": "ok"} with status 200 without database access or login."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login_opengraph_tags(client):
    """GET /login contains property="og:title", og:description, og:type, and meta description."""
    response = client.get("/login")
    assert response.status_code == 200
    assert 'property="og:title"' in response.text
    assert 'property="og:description"' in response.text
    assert 'property="og:type"' in response.text
    assert '<meta name="description"' in response.text
    assert 'content="Understand any codebase without reading every file."' in response.text

    showcase_resp = client.get("/showcase")
    assert showcase_resp.status_code == 200
    assert 'property="og:title"' in showcase_resp.text
    assert 'property="og:description"' in showcase_resp.text
    assert 'property="og:type"' in showcase_resp.text
    assert '<meta name="description"' in showcase_resp.text


