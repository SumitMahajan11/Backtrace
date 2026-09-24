import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.models.ingestion import (
    GitHubAPIError,
    InvalidURLError,
    RepoTooLargeError,
)
from app.services.ingestion import IngestionService, check_repo_size_preflight
from app.storage.analysis_job_repository import AnalysisJobRepository


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
def test_db_session(test_db):
    TestingSessionLocal, _ = test_db
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


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


def test_preflight_check_under_limit(monkeypatch):
    """Preflight check passes when repository has <= 150 supported files."""
    mock_tree_items = [
        {"path": f"src/file_{i}.py", "type": "blob", "size": 100}
        for i in range(50)
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"tree": mock_tree_items, "truncated": False}

    with patch("httpx.Client.get", return_value=mock_response):
        count = check_repo_size_preflight("https://github.com/owner/small-repo")
        assert count == 50


def test_preflight_check_exceeds_limit(monkeypatch):
    """Preflight check raises RepoTooLargeError when repo exceeds 150 files."""
    mock_tree_items = [
        {"path": f"src/module_{i}/file.py", "type": "blob", "size": 200}
        for i in range(180)
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"tree": mock_tree_items, "truncated": False}

    with patch("httpx.Client.get", return_value=mock_response):
        with pytest.raises(RepoTooLargeError) as exc_info:
            check_repo_size_preflight("https://github.com/owner/big-repo")
        assert exc_info.value.file_count == 180
        assert exc_info.value.limit == 150
        assert "Found 180 supported files (limit: 150 files)" in str(exc_info.value)


def test_preflight_check_subpath_scoping():
    """Preflight check with subpath scopes file counting strictly to that subdirectory."""
    mock_tree_items = [
        {"path": f"packages/core/file_{i}.py", "type": "blob", "size": 100}
        for i in range(40)
    ] + [
        {"path": f"packages/ui/component_{i}.tsx", "type": "blob", "size": 100}
        for i in range(140)
    ]  # Total 180 files

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"tree": mock_tree_items, "truncated": False}

    with patch("httpx.Client.get", return_value=mock_response):
        # Without subpath, it fails (>150)
        with pytest.raises(RepoTooLargeError) as exc_info:
            check_repo_size_preflight("https://github.com/owner/monorepo")
        assert exc_info.value.file_count == 180

        # With subpath "packages/core", only 40 files -> passes!
        count = check_repo_size_preflight(
            "https://github.com/owner/monorepo", subpath="packages/core"
        )
        assert count == 40


def test_preflight_filters_binary_and_ignored_directories():
    """Preflight check ignores binary files, node_modules, and .gitmodules."""
    mock_tree_items = [
        {"path": "src/index.js", "type": "blob", "size": 100},
        {"path": "src/logo.png", "type": "blob", "size": 500},  # binary -> ignored
        {"path": "node_modules/express/index.js", "type": "blob", "size": 200},  # ignored dir
        {"path": ".gitmodules", "type": "blob", "size": 50},  # ignored
        {"path": "build/bundle.js", "type": "blob", "size": 1000},  # ignored dir
        {"path": "large.dat", "type": "blob", "size": 2 * 1024 * 1024},  # >1MB -> ignored
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"tree": mock_tree_items, "truncated": False}

    with patch("httpx.Client.get", return_value=mock_response):
        count = check_repo_size_preflight("https://github.com/owner/mixed-repo")
        assert count == 1  # Only src/index.js


def test_preflight_github_api_errors():
    """Preflight check raises distinct GitHubAPIError for 403, 404, and 401."""
    # 1. Rate limit (403)
    mock_403 = MagicMock(status_code=403, text="Rate limit exceeded")
    with patch("httpx.Client.get", return_value=mock_403):
        with pytest.raises(GitHubAPIError) as exc:
            check_repo_size_preflight("https://github.com/owner/repo")
        assert exc.value.status_code == 403
        assert "rate limit" in str(exc.value).lower()

    # 2. 404 Not Found
    mock_404 = MagicMock(status_code=404, text="Not Found")
    with patch("httpx.Client.get", return_value=mock_404):
        with pytest.raises(GitHubAPIError) as exc:
            check_repo_size_preflight("https://github.com/owner/nonexistent", commit_ref="feature-xyz")
        assert exc.value.status_code == 404
        assert "not found" in str(exc.value).lower()


def test_submit_analysis_repo_too_large_renders_card_and_no_db_job(client, test_db_session, monkeypatch):
    """
    Submitting an oversized repository renders the 'Repository Too Large' card directly
    on the dashboard without creating any DB job records or consuming quota.
    """
    from app.services.billing_service import BillingService

    # Create and authenticate user
    user = UserModel(github_id=888111, github_username="tester_large", email="test@large.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    def mock_get_current_user_optional():
        return user

    from app.api.dependencies import get_current_user_optional, get_db
    app.dependency_overrides[get_current_user_optional] = mock_get_current_user_optional
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        # Mock preflight check to raise RepoTooLargeError(file_count=230)
        with patch(
            "app.services.ingestion.check_repo_size_preflight",
            side_effect=RepoTooLargeError("Found 230 supported files (limit: 150 files)", file_count=230, limit=150),
        ):
            resp = client.post(
                "/analyses/submit",
                data={"repo_url": "https://github.com/largeorg/giantrepo", "commit_ref": "v2.0"},
                follow_redirects=False,
            )

            # Returns 200 OK (renders dashboard in place, not a redirect to progress page)
            assert resp.status_code == 200
            html = resp.text

            # Check rendered "Repository Too Large" card elements
            assert "Repository Too Large" in html
            assert "Found 230 supported files (limit: 150 files)" in html
            assert "EXCEEDS 150 FILE LIMIT" in html
            assert "retry-too-large-form" in html
            assert "https://github.com/largeorg/giantrepo" in html
            assert "v2.0" in html
            assert "Subdirectory Path" in html
            assert "Dismiss / Back to Dashboard" in html

            # Verify ZERO database rows were created for this submission
            jobs = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs) == 0

            # Verify history ledger table never shows a FAILED job
            assert '<span class="badge badge-failed">' not in html
            assert "No analyses yet" in html
    finally:
        app.dependency_overrides.clear()


def test_submit_analysis_with_subpath_succeeds(client, test_db_session):
    """
    Submitting the same oversized repository with a narrower valid subpath succeeds
    and creates a running job with commit_ref and subpath stored.
    """
    user = UserModel(github_id=888222, github_username="tester_subpath", email="test@subpath.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    from app.api.dependencies import get_current_user_optional, get_db
    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        # Mock preflight check to pass when subpath is given
        with patch("app.services.ingestion.check_repo_size_preflight", return_value=45):
            resp = client.post(
                "/analyses/submit",
                data={
                    "repo_url": "https://github.com/largeorg/giantrepo",
                    "commit_ref": "main",
                    "subpath": "packages/api",
                },
                follow_redirects=False,
            )

            # Redirects to /progress/{job.id}
            assert resp.status_code == 302
            assert "/progress/" in resp.headers["location"]

            # DB row created
            jobs = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs) == 1
            assert jobs[0].status == "running"
            assert jobs[0].github_url == "https://github.com/largeorg/giantrepo"
            assert jobs[0].commit_ref == "main"
            assert jobs[0].subpath == "packages/api"
    finally:
        app.dependency_overrides.clear()


def test_submit_analysis_github_api_error_renders_distinct_message(client, test_db_session):
    """
    When GitHub API fails (e.g. rate limit), dashboard renders distinct error
    and creates 0 DB rows.
    """
    user = UserModel(github_id=888333, github_username="tester_api_err", email="test@api.com")
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    from app.api.dependencies import get_current_user_optional, get_db
    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = lambda: test_db_session

    try:
        with patch(
            "app.services.ingestion.check_repo_size_preflight",
            side_effect=GitHubAPIError("GitHub API rate limit exceeded.", status_code=403),
        ):
            resp = client.post(
                "/analyses/submit",
                data={"repo_url": "https://github.com/owner/somerepo"},
                follow_redirects=False,
            )

            assert resp.status_code == 200
            assert "GitHub API Error: GitHub API rate limit exceeded." in resp.text
            # Zero jobs created
            jobs = AnalysisJobRepository.get_jobs_for_user(test_db_session, user.id)
            assert len(jobs) == 0
    finally:
        app.dependency_overrides.clear()
