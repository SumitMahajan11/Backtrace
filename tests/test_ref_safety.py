from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user_optional, get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
from app.services.ingestion import IngestionService, validate_commit_ref
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


def test_validate_commit_ref_rejections():
    """
    Validates branch and commit_ref with ^[A-Za-z0-9][A-Za-z0-9._/@-]{0,199}$.
    Rejects:
    - '--orphan' (flag starting with '-')
    - '-x' (flag starting with '-')
    - 'main; rm -rf /' (shell injection)
    - 'a b' (spaces)
    """
    bad_refs = ["--orphan", "-x", "main; rm -rf /", "a b", "; ls", "-b", "foo bar", ""]
    for bad in ["--orphan", "-x", "main; rm -rf /", "a b"]:
        with pytest.raises(ValueError) as exc:
            validate_commit_ref(bad)
        assert "Invalid branch or commit reference" in str(exc.value)

    # Valid refs should pass
    valid_refs = ["main", "v1.0.0", "feature/my-branch", "HEAD", "commit_sha-123@org"]
    for val in valid_refs:
        assert validate_commit_ref(val) == val


def test_submit_analysis_ref_rejection_at_submit_time(client, test_db):
    """
    Tests that malicious or invalid refs are rejected at submit time:
    - '--orphan'
    - '-x'
    - 'main; rm -rf /'
    - 'a b'
    Contract: renders error message, creates no AnalysisJob row, starts no ingestion.
    """
    SessionLocal, _ = test_db
    user = UserModel(github_id=777666, github_username="ref_tester", email="ref@test.com")
    with SessionLocal() as session:
        session.add(user)
        session.commit()
        session.refresh(user)

    app.dependency_overrides[get_current_user_optional] = lambda: user

    try:
        bad_refs = ["--orphan", "-x", "main; rm -rf /", "a b"]
        for bad in bad_refs:
            resp = client.post(
                "/analyses/submit",
                data={
                    "repo_url": "https://github.com/owner/repo",
                    "commit_ref": bad,
                },
                follow_redirects=False,
            )
            assert resp.status_code == 200
            assert "Invalid branch or commit reference" in resp.text

            # Verify no job was created
            with SessionLocal() as session:
                jobs = AnalysisJobRepository.get_jobs_for_user(session, user.id)
                assert len(jobs) == 0
    finally:
        app.dependency_overrides.pop(get_current_user_optional, None)


def test_checkout_command_uses_detach_and_dashdash(tmp_path, monkeypatch):
    """
    Verifies that git checkout is built as ["checkout", "--detach", target_ref, "--"].
    """
    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    recorded_commands = []
    def mock_run_sandboxed_git_command(cmd, cwd=None, timeout_seconds=None):
        recorded_commands.append(list(cmd))
        mock_res = MagicMock()
        mock_res.stdout = "main"
        return mock_res

    monkeypatch.setattr("app.services.ingestion.run_sandboxed_git_command", mock_run_sandboxed_git_command)

    # Mock _process_file_tree to return empty
    service = IngestionService()
    monkeypatch.setattr(service, "_process_file_tree", lambda base_dir, subpath=None: ([], {}, []))
    monkeypatch.setattr(service, "_get_head_commit", lambda repo_dir: "c0ffee")
    monkeypatch.setattr(service, "_get_default_branch", lambda repo_dir: "main")

    service.ingest_repository("https://github.com/owner/repo", commit_ref="feature/auth")

    # Verify checkout command
    checkout_cmds = [cmd for cmd in recorded_commands if len(cmd) > 0 and cmd[0] == "checkout"]
    assert len(checkout_cmds) >= 1
    assert checkout_cmds[0] == ["checkout", "--detach", "feature/auth", "--"]
