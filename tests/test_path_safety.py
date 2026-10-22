import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user_optional, get_db
from app.db.session import Base
from app.main import app
from app.models.db import UserModel
from app.services.ingestion import IngestionService
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.utils.file_filter import sanitize_and_validate_subpath


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


def test_sanitize_and_validate_subpath_rejections():
    """
    Subpath validation strictly rejects:
    - absolute paths ("/etc")
    - drive letters ("C:\\x", "D:/dir")
    - backslashes ("a\\b")
    - directory traversal ("a/../../b")
    - null bytes ("\x00")
    """
    bad_subpaths = [
        "/etc",
        "/var/run/secrets",
        "C:\\x",
        "C:/x",
        "D:\\path",
        "a/../../b",
        "../../etc",
        "packages/../../secret",
        "foo\\bar",
        "sub\\dir",
        "\x00null",
        "null\0byte",
    ]

    for bad in bad_subpaths:
        with pytest.raises(ValueError) as exc_info:
            sanitize_and_validate_subpath(bad)
        assert len(str(exc_info.value)) > 0


def test_process_file_tree_skips_symlink_pointing_outside(tmp_path):
    """
    Verifies that symlinks pointing outside the repository clone directory are skipped
    and not included in file_contents.
    """
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "secret.txt"
    outside_file.write_text("SUPER_SECRET_EXTERNAL_CONTENT", encoding="utf-8")

    # Regular file inside clone
    inside_file = clone_dir / "main.py"
    inside_file.write_text("print('hello')", encoding="utf-8")

    # Symlink inside clone pointing outside
    symlink_file = clone_dir / "external_link.py"
    try:
        symlink_file.symlink_to(outside_file)
    except OSError:
        pytest.skip("Creating symlinks requires privileges or Developer Mode on this OS")

    service = IngestionService()
    file_tree, file_contents, skipped_items = service._process_file_tree(clone_dir)

    # Regular file is read
    assert "main.py" in file_contents
    assert file_contents["main.py"] == "print('hello')"

    # Symlink pointing outside is skipped
    assert "external_link.py" not in file_contents
    assert not any("SUPER_SECRET" in content for content in file_contents.values())
    assert any("symlink" in s.reason for s in skipped_items)


def test_process_file_tree_subpath_outside_clone_raises(tmp_path):
    """
    Verifies that if subpath resolves outside the clone directory, _process_file_tree
    raises ValueError before reading any file.
    """
    clone_dir = tmp_path / "clone"
    clone_dir.mkdir()
    (clone_dir / "main.py").write_text("print('test')", encoding="utf-8")

    service = IngestionService()
    with pytest.raises(ValueError, match="resolves outside clone directory"):
        service._process_file_tree(clone_dir, subpath="../../etc")


def test_submit_analysis_subpath_rejection_at_submit_time(client, test_db):
    """
    Tests that bad subpaths are rejected at submit time without network access:
    - "/etc"
    - "C:\\x"
    - "a/../../b"
    Returns 200 with error message and creates 0 AnalysisJob rows.
    """
    SessionLocal, _ = test_db
    user = UserModel(github_id=999888, github_username="path_tester", email="path@test.com")
    with SessionLocal() as session:
        session.add(user)
        session.commit()
        session.refresh(user)

    app.dependency_overrides[get_current_user_optional] = lambda: user

    try:
        bad_inputs = ["/etc", "C:\\x", "a/../../b"]
        for bad in bad_inputs:
            resp = client.post(
                "/analyses/submit",
                data={
                    "repo_url": "https://github.com/owner/repo",
                    "subpath": bad,
                },
                follow_redirects=False,
            )
            assert resp.status_code == 200
            assert "Invalid subdirectory path" in resp.text

            # Verify no job was created
            with SessionLocal() as session:
                jobs = AnalysisJobRepository.get_jobs_for_user(session, user.id)
                assert len(jobs) == 0
    finally:
        app.dependency_overrides.pop(get_current_user_optional, None)
