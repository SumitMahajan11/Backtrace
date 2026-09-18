"""Tests for Piston Integration and Execution Verification Engine (Prompt 15)."""

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import MilestoneAttemptModel, UserModel
from app.security.auth import create_access_token
from app.services.execution_verifier import (
    ExecutionVerifier,
    ExecutionVerifierConnectionError,
    ExecutionVerifierError,
)
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.storage.user_repository import UserRepository
from app.utils.file_filter import MAX_FILE_SIZE_BYTES


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


@pytest.fixture
def create_user(test_db):
    SessionLocal, _ = test_db

    def _create(github_id: int, username: str) -> UserModel:
        with SessionLocal() as session:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=github_id,
                github_username=username,
                email=f"{username}@example.com",
            )
            session.commit()
            session.refresh(user)
            return user

    return _create


@pytest.fixture
def create_job(test_db):
    SessionLocal, _ = test_db

    def _create(user_id: int, graph_data: dict) -> int:
        with SessionLocal() as session:
            job = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                repo_name="test-org/test-repo",
                github_url="https://github.com/test-org/test-repo",
                run_id="run_exec_test_01",
            )
            job.status = "complete"
            job.graph_data = graph_data
            session.commit()
            return job.id

    return _create


# =========================================================================
# Unit Tests for ExecutionVerifier Service
# =========================================================================

def test_language_normalization():
    verifier = ExecutionVerifier()
    assert verifier.normalize_language("python") == "python"
    assert verifier.normalize_language("py") == "python"
    assert verifier.normalize_language("js") == "javascript"
    assert verifier.normalize_language("typescript") == "typescript"
    assert verifier.normalize_language("sh") == "bash"
    assert verifier.normalize_language("golang") == "go"


def test_filename_mapping():
    verifier = ExecutionVerifier()
    assert verifier._get_filename_for_language("python") == "solution.py"
    assert verifier._get_filename_for_language("javascript") == "solution.js"
    assert verifier._get_filename_for_language("bash") == "solution.sh"
    assert verifier._get_filename_for_language("unknown_lang") == "solution.unknown_lang"


def test_output_truncation():
    verifier = ExecutionVerifier(max_output_chars=50)
    small_text = "Hello world"
    text_out, truncated = verifier._truncate_output(small_text)
    assert text_out == "Hello world"
    assert truncated is False

    large_text = "A" * 100
    text_out, truncated = verifier._truncate_output(large_text)
    assert truncated is True
    assert "Output truncated" in text_out
    assert len(text_out) > 50  # contains prefix + notice


def test_verifier_mocked_success():
    verifier = ExecutionVerifier()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "language": "python",
        "version": "3.10.0",
        "run": {
            "stdout": "Computation result: 42\n",
            "stderr": "",
            "code": 0,
            "signal": None,
        }
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        res = verifier.execute(submitted_code="print(42)", language="python")
        assert res["status"] == "success"
        assert res["exit_code"] == 0
        assert "Computation result: 42" in res["stdout"]
        assert res["truncated"] is False


def test_verifier_mocked_compile_failure():
    verifier = ExecutionVerifier()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "language": "cpp",
        "version": "10.2.0",
        "compile": {
            "stdout": "",
            "stderr": "error: expected ';' before '}' token",
            "code": 1,
            "signal": None,
        },
        "run": {
            "stdout": "",
            "stderr": "",
            "code": None,
            "signal": None,
        }
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        res = verifier.execute(submitted_code="int main() {}", language="cpp")
        assert res["status"] == "error"
        assert res["exit_code"] == 1
        assert "error: expected" in res["stderr"]


def test_verifier_mocked_timeout():
    verifier = ExecutionVerifier()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "language": "python",
        "version": "3.10.0",
        "run": {
            "stdout": "",
            "stderr": "Sandbox keeper timed out",
            "code": None,
            "signal": "SIGKILL",
            "message": "Time limit exceeded",
        }
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        res = verifier.execute(submitted_code="while True: pass", language="python")
        assert res["status"] == "timeout"
        assert res["signal"] == "SIGKILL"


def test_verifier_connection_failure():
    import httpx
    verifier = ExecutionVerifier()
    with patch("httpx.Client.post", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(ExecutionVerifierConnectionError):
            verifier.execute(submitted_code="print(1)", language="python")


# =========================================================================
# Integration Tests for POST /attempts/{job_id}/{milestone_tier}/run API
# =========================================================================

def test_api_run_idor_protection(client, create_user, create_job):
    user_a = create_user(github_id=9001, username="usera")
    user_b = create_user(github_id=9002, username="userb")
    job_id = create_job(user_id=user_a.id, graph_data={"tiers": {"1": []}})

    token_b = create_access_token(user_id=user_b.id, github_id=user_b.github_id, github_username=user_b.github_username)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp = client.post(
        f"/attempts/{job_id}/1/run",
        json={"submitted_code": "print('hello')", "language": "python"},
        headers=headers_b,
    )
    assert resp.status_code == 403
    assert "Access forbidden" in resp.json()["detail"]


def test_api_run_job_not_found(client, create_user):
    user_a = create_user(github_id=9003, username="usera3")
    token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    resp = client.post(
        "/attempts/99999/1/run",
        json={"submitted_code": "print('hello')", "language": "python"},
        headers=headers_a,
    )
    assert resp.status_code == 404


def test_api_run_payload_size_dos_defense(client, create_user, create_job):
    user_a = create_user(github_id=9004, username="usera4")
    job_id = create_job(user_id=user_a.id, graph_data={"tiers": {"1": []}})

    token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    oversized_code = "A" * (MAX_FILE_SIZE_BYTES + 50)
    resp = client.post(
        f"/attempts/{job_id}/1/run",
        json={"submitted_code": oversized_code, "language": "python"},
        headers=headers_a,
    )
    assert resp.status_code == 413


def test_api_run_success_persists_last_run_state(client, create_user, create_job, test_db):
    SessionLocal, _ = test_db
    user_a = create_user(github_id=9005, username="usera5")
    job_id = create_job(user_id=user_a.id, graph_data={"tiers": {"1": []}})

    token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    mock_exec_result = {
        "language": "python",
        "version": "3.10.0",
        "stdout": "Real Piston Execution Output 42\n",
        "stderr": "",
        "exit_code": 0,
        "signal": None,
        "execution_time_ms": 124.5,
        "status": "success",
        "truncated": False,
        "raw_response": {},
    }

    with patch.object(ExecutionVerifier, "execute", return_value=mock_exec_result):
        resp = client.post(
            f"/attempts/{job_id}/1/run",
            json={"submitted_code": "print(42)", "language": "python"},
            headers=headers_a,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution"]["stdout"] == "Real Piston Execution Output 42\n"
        assert data["execution"]["exit_code"] == 0
        assert data["attempt"]["last_run_stdout"] == "Real Piston Execution Output 42\n"
        assert data["attempt"]["last_run_exit_code"] == 0
        assert data["attempt"]["last_run_at"] is not None
        # Prompt 16 requirement: Run endpoint NEVER touches status or counts as an attempt
        assert data["attempt"]["status"] == "not_started"

        # Verify DB persisted row directly
        with SessionLocal() as session:
            attempt = MilestoneAttemptRepository.get_attempt(session, user_a.id, job_id, 1)
            assert attempt is not None
            assert attempt.last_run_stdout == "Real Piston Execution Output 42\n"
            assert attempt.last_run_exit_code == 0
            assert attempt.last_run_at is not None
            assert attempt.status == "not_started"


def test_prompt16_run_vs_submit_lifecycle(client, create_user, create_job, test_db):
    """Prompt 16 lifecycle test:
    - Multiple Run calls update last_run_* but status stays not_started.
    - Submit call performs AST verification AND execution, transitioning status to attempting/structurally_verified.
    """
    SessionLocal, _ = test_db
    user = create_user(github_id=9006, username="lifecycle_tester")
    job_id = create_job(user_id=user.id, graph_data={
        "nodes": [{"id": "math_mod.py", "tier": 1, "exports": ["compute_val"]}]
    })

    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    headers = {"Authorization": f"Bearer {token}"}

    mock_run_1 = {
        "language": "python",
        "version": "3.10.0",
        "stdout": "First Run Output\n",
        "stderr": "",
        "exit_code": 0,
        "signal": None,
        "execution_time_ms": 50.0,
        "status": "success",
        "truncated": False,
        "raw_response": {},
    }
    mock_run_2 = {
        "language": "python",
        "version": "3.10.0",
        "stdout": "Second Run Output (Calculation: 42)\n",
        "stderr": "",
        "exit_code": 0,
        "signal": None,
        "execution_time_ms": 55.0,
        "status": "success",
        "truncated": False,
        "raw_response": {},
    }
    mock_submit_run = {
        "language": "python",
        "version": "3.10.0",
        "stdout": "Submit Execution 100\n",
        "stderr": "",
        "exit_code": 0,
        "signal": None,
        "execution_time_ms": 60.0,
        "status": "success",
        "truncated": False,
        "raw_response": {},
    }

    # 1. First Run: Updates last_run_*, status stays not_started
    with patch.object(ExecutionVerifier, "execute", return_value=mock_run_1):
        resp1 = client.post(
            f"/attempts/{job_id}/1/run",
            json={"submitted_code": "print('First Run Output')"},
            headers=headers,
        )
        assert resp1.status_code == 200
        assert resp1.json()["attempt"]["status"] == "not_started"
        assert resp1.json()["attempt"]["last_run_stdout"] == "First Run Output\n"

    # 2. Second Run: Updates last_run_*, status still stays not_started
    with patch.object(ExecutionVerifier, "execute", return_value=mock_run_2):
        resp2 = client.post(
            f"/attempts/{job_id}/1/run",
            json={"submitted_code": "print('Second Run Output (Calculation: 42)')"},
            headers=headers,
        )
        assert resp2.status_code == 200
        assert resp2.json()["attempt"]["status"] == "not_started"
        assert resp2.json()["attempt"]["last_run_stdout"] == "Second Run Output (Calculation: 42)\n"

    # Verify in DB: exactly one attempt record with status=not_started
    with SessionLocal() as session:
        att = MilestoneAttemptRepository.get_attempt(session, user.id, job_id, 1)
        assert att is not None
        assert att.status == "not_started"
        assert att.last_run_stdout == "Second Run Output (Calculation: 42)\n"

    # 3. Submit: Runs AST verification + execution, transitions status to structurally_verified
    with patch.object(ExecutionVerifier, "execute", return_value=mock_submit_run):
        resp_sub = client.post(
            f"/attempts/{job_id}/1",
            json={"submitted_code": "def compute_val(): return 100\nprint('Submit Execution 100')"},
            headers=headers,
        )
        assert resp_sub.status_code == 200
        data_sub = resp_sub.json()
        assert data_sub["attempt"]["status"] == "structurally_verified"
        assert data_sub["verification"]["structurally_verified"] is True
        assert data_sub["execution"]["stdout"] == "Submit Execution 100\n"

    # Verify in DB: status is now structurally_verified, last_run_* updated to submit run
    with SessionLocal() as session:
        att_final = MilestoneAttemptRepository.get_attempt(session, user.id, job_id, 1)
        assert att_final.status == "structurally_verified"
        assert att_final.last_run_stdout == "Submit Execution 100\n"



# =========================================================================
# Live Piston Execution Tests (Run if local Piston is active)
# =========================================================================

@pytest.mark.skipif(
    not ExecutionVerifier().get_runtimes if False else False,  # Evaluated in test
    reason="Piston live daemon check",
)
def test_live_piston_three_languages():
    verifier = ExecutionVerifier()
    try:
        runtimes = verifier.get_runtimes()
    except Exception:
        pytest.skip("Piston daemon not running locally")

    # Python
    py_res = verifier.execute("print('Hello ' + str(6 * 7))", language="python")
    assert py_res["exit_code"] == 0
    assert "Hello 42" in py_res["stdout"]

    # JS
    js_res = verifier.execute("console.log('Hello ' + (6 * 7));", language="javascript")
    assert js_res["exit_code"] == 0
    assert "Hello 42" in js_res["stdout"]

    # Bash
    sh_res = verifier.execute("echo 'Hello '$((6 * 7))", language="bash")
    assert sh_res["exit_code"] == 0
    assert "Hello 42" in sh_res["stdout"]


def test_live_piston_network_isolation():
    verifier = ExecutionVerifier()
    try:
        verifier.get_runtimes()
    except Exception:
        pytest.skip("Piston daemon not running locally")

    net_code = """
import socket, sys
try:
    s = socket.create_connection(('1.1.1.1', 80), timeout=1)
    s.close()
    print("CONNECTED")
except Exception as e:
    print(f"BLOCKED:{type(e).__name__}", file=sys.stderr)
"""
    res = verifier.execute(net_code, language="python")
    assert "CONNECTED" not in res["stdout"]
    assert "BLOCKED:" in res["stderr"] or "Network is unreachable" in res["stderr"] or "Temporary failure" in res["stderr"]
