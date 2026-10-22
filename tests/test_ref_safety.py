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
    bad_refs = ["--orphan", "-x", "-f", "--force", "--quiet", "main; rm -rf /", "a b", "; ls", "-b", "foo bar", ""]
    for bad in ["--orphan", "-x", "-f", "--force", "--quiet", "main; rm -rf /", "a b"]:
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
        bad_refs = ["--orphan", "-x", "-f", "--force", "--quiet", "main; rm -rf /", "a b"]
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


def test_checkout_command_tries_origin_ref_first(tmp_path, monkeypatch):
    """
    Verifies that checkout tries origin/<ref> first. When origin/<ref> succeeds,
    it should be ["checkout", "--detach", "origin/feature/auth", "--"].
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

    service = IngestionService()
    monkeypatch.setattr(service, "_process_file_tree", lambda base_dir, subpath=None: ([], {}, []))
    monkeypatch.setattr(service, "_get_head_commit", lambda repo_dir: "c0ffee")
    monkeypatch.setattr(service, "_get_default_branch", lambda repo_dir: "main")

    service.ingest_repository("https://github.com/owner/repo", commit_ref="feature/auth")

    checkout_cmds = [cmd for cmd in recorded_commands if len(cmd) > 0 and cmd[0] == "checkout"]
    assert len(checkout_cmds) >= 1
    # origin/ref is tried first
    assert checkout_cmds[0] == ["checkout", "--detach", "origin/feature/auth", "--"]


def test_checkout_falls_back_to_bare_ref_when_origin_fails(tmp_path, monkeypatch):
    """
    When origin/<ref> fails (e.g. for a tag or commit SHA), checkout should
    fall back to the bare ref.
    """
    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    recorded_commands = []
    def mock_run_sandboxed_git_command(cmd, cwd=None, timeout_seconds=None):
        recorded_commands.append(list(cmd))
        # Fail if cmd contains "origin/" prefix
        if any("origin/" in str(c) for c in cmd):
            raise RuntimeError("no such ref: origin/v1.0.0")
        mock_res = MagicMock()
        mock_res.stdout = "main"
        return mock_res

    monkeypatch.setattr("app.services.ingestion.run_sandboxed_git_command", mock_run_sandboxed_git_command)

    service = IngestionService()
    monkeypatch.setattr(service, "_process_file_tree", lambda base_dir, subpath=None: ([], {}, []))
    monkeypatch.setattr(service, "_get_head_commit", lambda repo_dir: "c0ffee")
    monkeypatch.setattr(service, "_get_default_branch", lambda repo_dir: "main")

    service.ingest_repository("https://github.com/owner/repo", commit_ref="v1.0.0")

    checkout_cmds = [cmd for cmd in recorded_commands if len(cmd) > 0 and cmd[0] == "checkout"]
    assert len(checkout_cmds) == 2  # origin/v1.0.0 failed, then v1.0.0 succeeded
    assert checkout_cmds[0] == ["checkout", "--detach", "origin/v1.0.0", "--"]
    assert checkout_cmds[1] == ["checkout", "--detach", "v1.0.0", "--"]


def test_checkout_raises_when_ref_not_found(tmp_path, monkeypatch):
    """
    When both origin/<ref> and bare <ref> fail, an InvalidURLError should be
    raised. It must NOT silently fall back to HEAD.
    """
    from app.services.ingestion import InvalidURLError

    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    call_count = 0
    def mock_run_sandboxed_git_command(cmd, cwd=None, timeout_seconds=None):
        nonlocal call_count
        call_count += 1
        if cmd[0] == "clone":
            mock_res = MagicMock()
            mock_res.stdout = ""
            return mock_res
        if cmd[0] == "checkout":
            raise RuntimeError(f"fatal: reference is not a tree: {cmd}")
        mock_res = MagicMock()
        mock_res.stdout = ""
        return mock_res

    monkeypatch.setattr("app.services.ingestion.run_sandboxed_git_command", mock_run_sandboxed_git_command)

    service = IngestionService()

    with pytest.raises(InvalidURLError, match="Could not check out ref"):
        service.ingest_repository("https://github.com/owner/repo", commit_ref="nonexistent-branch-xyz")


def test_ingestion_rejects_hyphen_refs_in_validator_and_before_checkout(tmp_path, monkeypatch):
    """
    Verifies that ingest_repository rejects refs starting with '-' (e.g. '-f', '--force', '--quiet')
    both in the validator and as a defense-in-depth gate before checkout, ensuring git checkout
    is never executed with options disguised as branch names.
    """
    from app.services.ingestion import InvalidURLError

    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("test", "repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    checkout_commands = []
    def mock_run_sandboxed_git_command(cmd, cwd=None, timeout_seconds=None):
        if len(cmd) > 0 and cmd[0] == "checkout":
            checkout_commands.append(list(cmd))
        mock_res = MagicMock()
        mock_res.stdout = ""
        return mock_res

    monkeypatch.setattr("app.services.ingestion.run_sandboxed_git_command", mock_run_sandboxed_git_command)

    service = IngestionService()

    # 1. Normal path: validate_commit_ref rejects '-f', '--force', '--quiet'
    for flag in ["-f", "--force", "--quiet"]:
        checkout_commands.clear()
        with pytest.raises(InvalidURLError) as exc:
            service.ingest_repository("https://github.com/owner/repo", commit_ref=flag)
        assert "References starting with '-' are not allowed" in str(exc.value) or "Invalid branch or commit reference" in str(exc.value)
        assert len(checkout_commands) == 0

    # 2. Defense-in-depth: if validate_commit_ref were bypassed, ingestion rejects before checkout
    monkeypatch.setattr("app.services.ingestion.validate_commit_ref", lambda ref: ref)
    for flag in ["-f", "--force", "--quiet"]:
        checkout_commands.clear()
        with pytest.raises(InvalidURLError) as exc:
            service.ingest_repository("https://github.com/owner/repo", commit_ref=flag)
        assert "references starting with '-' are not allowed" in str(exc.value)
        assert len(checkout_commands) == 0


