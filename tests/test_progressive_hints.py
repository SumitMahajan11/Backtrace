"""Unit and integration test suite for Progressive Hint Gate (Prompt 13).

Covers:
1. Tone-aligned confirmation copy variants and selection.
2. Hint 1 conceptual-only generation and rigorous anti-leak verification against symbol table.
3. Synthetic leak test verifying HintLeakError is raised if an exact expected symbol is present.
4. Hint 2 generation with target symbols and file paths, verifying zero literal code.
5. Reference implementation skeleton generation.
6. Progressive Hint API lifecycle (/hint -> level 1 -> /hint -> level 2).
7. "Try first" gate rejection on untouched milestones.
8. Separate "Reveal Implementation" action (/reveal) persisting implementation_revealed = True.
9. IDOR protection across all hint and reveal endpoints.
"""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_current_user, get_db
from app.db.session import Base
from app.main import app
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, UserModel
from app.services.hint_engine import HintEngine, HintLeakError
from app.services.structural_verifier import StructuralVerifier
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository


# Sample graph fixtures for testing
SAMPLE_GRAPH_DATA = {
    "nodes": [
        {
            "id": "app/core/config.py",
            "path": "app/core/config.py",
            "tier": 0,
            "domain": "core",
            "type": "core",
            "symbols": [
                {"name": "Settings", "kind": "class"},
                {"name": "get_settings", "kind": "function", "args": []},
            ],
        },
        {
            "id": "app/services/auth_service.py",
            "path": "app/services/auth_service.py",
            "tier": 1,
            "domain": "services",
            "type": "service",
            "symbols": [
                {"name": "AuthService", "kind": "class"},
                {"name": "verify_token", "kind": "function", "args": ["token"]},
            ],
        },
        {
            "id": "app/api/endpoints.py",
            "path": "app/api/endpoints.py",
            "tier": 2,
            "domain": "api",
            "type": "api",
            "symbols": [
                {"name": "login_handler", "kind": "function", "args": ["req"]},
            ],
        },
    ],
    "edges": [
        {"source": "app/services/auth_service.py", "target": "app/core/config.py"},
        {"source": "app/api/endpoints.py", "target": "app/services/auth_service.py"},
    ],
}


class TestHintEngine:
    """Unit tests for HintEngine logic and anti-leak guarantees."""

    def test_confirmation_copy_variants_exist(self):
        """Ensures at least 2-3 real non-mocking copy variants exist and one is selected."""
        assert len(HintEngine.CONFIRM_COPY_VARIANTS) >= 3
        assert HintEngine.SELECTED_HINT_1_CONFIRM in HintEngine.CONFIRM_COPY_VARIANTS
        assert "Take another few minutes" in HintEngine.SELECTED_HINT_1_CONFIRM
        assert HintEngine.CONFIRM_HINT_2_COPY
        assert HintEngine.CONFIRM_REVEAL_COPY

    def test_hint_1_conceptual_no_leaks(self):
        """Verifies Hint 1 references architecture and domain, with zero exact symbol leaks."""
        hint_0 = HintEngine.get_hint_1(SAMPLE_GRAPH_DATA, milestone_tier=0)
        assert "CORE" in hint_0
        assert "foundation layer" in hint_0

        # Symbol leak verification
        expected_syms_0 = StructuralVerifier.extract_expected_symbols_from_graph(SAMPLE_GRAPH_DATA, 0)
        for sym in expected_syms_0:
            sym_name = sym["name"]
            assert sym_name.lower() not in hint_0.lower().split()

        hint_1 = HintEngine.get_hint_1(SAMPLE_GRAPH_DATA, milestone_tier=1)
        assert "SERVICES" in hint_1
        expected_syms_1 = StructuralVerifier.extract_expected_symbols_from_graph(SAMPLE_GRAPH_DATA, 1)
        for sym in expected_syms_1:
            sym_name = sym["name"]
            assert sym_name.lower() not in hint_1.lower().split()

    def test_hint_1_leak_detection_raises_error(self):
        """Ensures verify_hint_1_no_leaks catches accidental symbol leaks and raises HintLeakError."""
        leaky_hint = "Make sure you instantiate the Settings class and call get_settings."
        expected_syms = [{"name": "Settings", "kind": "class"}, {"name": "get_settings", "kind": "function"}]

        with pytest.raises(HintLeakError) as exc_info:
            HintEngine.verify_hint_1_no_leaks(leaky_hint, expected_syms)

        assert "Hint 1 leak violation" in str(exc_info.value)
        assert "Settings" in str(exc_info.value)

    def test_hint_2_generation_zero_literal_code(self):
        """Verifies Hint 2 identifies missing symbols and files with zero literal implementation code."""
        missing = [{"expected": {"name": "AuthService", "kind": "class"}}]
        hint_2 = HintEngine.get_hint_2(SAMPLE_GRAPH_DATA, milestone_tier=1, missing_symbols=missing)

        assert "`app/services/auth_service.py`" in hint_2
        assert "`AuthService` (class)" in hint_2

        # Verify zero literal code (no code syntax lines)
        assert "def " not in hint_2
        assert "class AuthService:" not in hint_2
        assert "return " not in hint_2
        assert "{" not in hint_2

    def test_reference_implementation_generation(self):
        """Verifies that reference implementation contains valid structural python skeleton."""
        ref = HintEngine.get_reference_implementation(SAMPLE_GRAPH_DATA, milestone_tier=0)
        assert ref["milestone_tier"] == 0
        code = ref["reference_code"]
        assert "class Settings:" in code
        assert "def get_settings():" in code
        assert "def __init__(self):" in code


class TestProgressiveHintAPI:
    """Integration tests for progressive hint API endpoints and IDOR protections."""

    @pytest.fixture
    def test_db_session(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        Base.metadata.create_all(bind=engine)
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
            Base.metadata.drop_all(bind=engine)

    @pytest.fixture
    def setup_user_and_job(self, test_db_session):
        user_a = UserModel(
            id=101,
            github_id="101",
            github_username="architect_alice",
            created_at=None,
        )
        user_b = UserModel(
            id=102,
            github_id="102",
            github_username="adversary_bob",
            created_at=None,
        )
        test_db_session.add_all([user_a, user_b])
        test_db_session.commit()

        job_a = AnalysisJobModel(
            id=201,
            user_id=user_a.id,
            repo_name="alice-repo",
            github_url="https://github.com/org/alice-repo",
            run_id="run-alice-201",
            status="completed",
            graph_data=SAMPLE_GRAPH_DATA,
        )
        test_db_session.add(job_a)
        test_db_session.commit()
        return user_a, user_b, job_a

    def test_hint_gate_try_first_policy(self, setup_user_and_job, test_db_session):
        """Verifies hints are locked (HTTP 400) if milestone has not been attempted yet."""
        user_a, _, job_a = setup_user_and_job

        def override_get_current_user():
            return user_a

        def override_get_db():
            yield test_db_session

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db

        try:
            client = TestClient(app)
            resp = client.post(f"/api/attempts/{job_a.id}/0/hint")
            assert resp.status_code == status.HTTP_400_BAD_REQUEST
            assert "Hints are locked until you make your first implementation attempt" in resp.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_progressive_hint_lifecycle_and_db_persistence(self, setup_user_and_job, test_db_session):
        """Verifies 1st submit -> unlock -> hint 1 -> hint 2 -> implementation reveal lifecycle."""
        user_a, _, job_a = setup_user_and_job

        def override_get_current_user():
            return user_a

        def override_get_db():
            yield test_db_session

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db

        try:
            client = TestClient(app)

            # Step 1: Submit code (Attempting)
            sub_resp = client.post(
                f"/api/attempts/{job_a.id}/0",
                json={"submitted_code": "class IncompleteSettings:\n    pass\n"},
            )
            assert sub_resp.status_code == 200
            assert sub_resp.json()["attempt"]["status"] == "attempting"

            attempt_row = MilestoneAttemptRepository.get_attempt(test_db_session, user_a.id, job_a.id, 0)
            assert attempt_row is not None
            assert attempt_row.hint_level_revealed == 0
            assert attempt_row.implementation_revealed is False

            # Step 2: Request Hint 1
            h1_resp = client.post(f"/api/attempts/{job_a.id}/0/hint")
            assert h1_resp.status_code == 200
            h1_data = h1_resp.json()
            assert h1_data["hint_level_revealed"] == 1
            assert "Milestone 0 forms the foundation layer" in h1_data["hint_1"]
            assert h1_data["hint_2"] is None

            test_db_session.refresh(attempt_row)
            assert attempt_row.hint_level_revealed == 1
            assert attempt_row.implementation_revealed is False

            # Step 3: Request Hint 2
            h2_resp = client.post(f"/api/attempts/{job_a.id}/0/hint")
            assert h2_resp.status_code == 200
            h2_data = h2_resp.json()
            assert h2_data["hint_level_revealed"] == 2
            assert h2_data["hint_2"] is not None
            assert "Missing AST contracts to declare" in h2_data["hint_2"]

            test_db_session.refresh(attempt_row)
            assert attempt_row.hint_level_revealed == 2
            assert attempt_row.implementation_revealed is False

            # Step 4: Separate Reveal Action
            rev_resp = client.post(f"/api/attempts/{job_a.id}/0/reveal")
            assert rev_resp.status_code == 200
            rev_data = rev_resp.json()
            assert rev_data["implementation_revealed"] is True
            assert "class Settings:" in rev_data["reference_implementation"]["reference_code"]

            test_db_session.refresh(attempt_row)
            assert attempt_row.implementation_revealed is True
            assert attempt_row.hint_level_revealed == 2
        finally:
            app.dependency_overrides.clear()

    def test_hint_and_reveal_idor_protection(self, setup_user_and_job, test_db_session):
        """Verifies User B cannot request hints or reveal implementations for User A's jobs."""
        user_a, user_b, job_a = setup_user_and_job

        # Ensure attempt exists for User A
        MilestoneAttemptRepository.save_or_update_attempt(
            session=test_db_session,
            user_id=user_a.id,
            job_id=job_a.id,
            milestone_tier=0,
            submitted_code="class Foo: pass",
            status="attempting",
        )

        # Authenticate as User B
        def override_get_current_user():
            return user_b

        def override_get_db():
            yield test_db_session

        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_db] = override_get_db

        try:
            client = TestClient(app)

            # IDOR on hint endpoint
            hint_resp = client.post(f"/api/attempts/{job_a.id}/0/hint")
            assert hint_resp.status_code == status.HTTP_403_FORBIDDEN
            assert "Access forbidden" in hint_resp.json()["detail"]

            # IDOR on reveal endpoint
            reveal_resp = client.post(f"/api/attempts/{job_a.id}/0/reveal")
            assert reveal_resp.status_code == status.HTTP_403_FORBIDDEN
            assert "Access forbidden" in reveal_resp.json()["detail"]

            # IDOR on GET attempt endpoint
            get_resp = client.get(f"/api/attempts/{job_a.id}/0")
            assert get_resp.status_code == status.HTTP_403_FORBIDDEN
        finally:
            app.dependency_overrides.clear()
