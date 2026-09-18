import pytest
import json
from app.services.grading_engine import GradingEngine
from app.services.curated_milestone_expectations import CuratedExpectationsRegistry
from app.services.structural_verifier import StructuralVerifier
from app.models.db import MilestoneAttemptModel, AnalysisJobModel, UserModel
from app.db.session import get_db_session, init_db
from app.services.piston_health import piston_health_monitor

piston_health_monitor.check_health_sync()


class MockJob:
    def __init__(self, repo_url="https://github.com/example/repo", repo_name="example/repo", graph_data=None):
        self.id = "mock_job_id"
        self.repo_url = repo_url
        self.repo_name = repo_name
        self.github_url = repo_url
        self.graph_data = graph_data or {}


def test_determine_grading_tier_real_tests_milestone_code():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {
                "tier": 1,
                "test_code": "def test_addition(): assert 1 + 1 == 2",
                "included_files": ["math_utils.py"]
            }
        ]
    }
    job = MockJob(graph_data=graph_data)
    tier, meta = engine.determine_grading_tier(job, 1, graph_data)
    assert tier == "real_tests"
    assert "test_addition" in meta["test_code"]


def test_determine_grading_tier_real_tests_graph_tests():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {"tier": 2, "included_files": ["core/calc.py"]}
        ],
        "tests": {
            "2": "def test_calc(): pass"
        }
    }
    job = MockJob(graph_data=graph_data)
    tier, meta = engine.determine_grading_tier(job, 2, graph_data)
    assert tier == "real_tests"
    assert "test_calc" in meta["test_code"]


def test_determine_grading_tier_expected_output():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {"tier": 1, "included_files": ["models.py"]}
        ]
    }
    job = MockJob(repo_url="https://github.com/psf/requests", repo_name="psf/requests", graph_data=graph_data)
    tier, meta = engine.determine_grading_tier(job, 1, graph_data)
    assert tier == "expected_output"
    assert "status=200" in meta["expected_stdout"]


def test_determine_grading_tier_structural_fallback():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {"tier": 1, "included_files": ["unknown.py"]}
        ]
    }
    job = MockJob(repo_url="https://github.com/custom/obscure-repo", repo_name="custom/obscure-repo", graph_data=graph_data)
    tier, meta = engine.determine_grading_tier(job, 1, graph_data)
    assert tier == "structural_only"


def test_grade_attempt_tier_1_real_tests_passing():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {
                "tier": 1,
                "test_code": "assert add(2, 3) == 5\nassert add(-1, 1) == 0\nprint('ALL TESTS PASSED')",
                "included_files": ["adder.py"],
                "exported_symbols": ["add"]
            }
        ],
        "nodes": [
            {"id": "adder.py", "tier": 1, "exports": ["add"]}
        ]
    }
    job = MockJob(graph_data=graph_data)
    user_code = "def add(a, b):\n    return a + b\n"
    
    result = engine.grade_attempt(job, 1, user_code, "python", graph_data)
    assert result["grading_method"] == "real_tests"
    assert result["passed"] is True
    assert result["status"] == "structurally_verified"
    assert result["execution"]["exit_code"] == 0


def test_grade_attempt_tier_1_real_tests_failing():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {
                "tier": 1,
                "test_code": "assert multiply(2, 3) == 6",
                "included_files": ["math.py"],
                "exported_symbols": ["multiply"]
            }
        ],
        "nodes": [
            {"id": "math.py", "tier": 1, "exports": ["multiply"]}
        ]
    }
    job = MockJob(graph_data=graph_data)
    # Incorrect code
    user_code = "def multiply(a, b):\n    return a + b\n"
    
    result = engine.grade_attempt(job, 1, user_code, "python", graph_data)
    assert result["grading_method"] == "real_tests"
    assert result["passed"] is False
    assert result["status"] == "attempting"


def test_grade_attempt_tier_2_expected_output_passing():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {"tier": 1, "included_files": ["status.py"], "exported_symbols": []}
        ],
        "nodes": [
            {"id": "status.py", "tier": 1, "exports": []}
        ]
    }
    job = MockJob(repo_url="https://github.com/psf/requests", repo_name="psf/requests", graph_data=graph_data)
    user_code = "print('HTTP Adapter initialized: max_retries=3, status=200')\n"
    
    result = engine.grade_attempt(job, 1, user_code, "python", graph_data)
    assert result["grading_method"] == "expected_output"
    assert result["passed"] is True
    assert result["status"] == "structurally_verified"
    assert result["execution"]["exit_code"] == 0


def test_grade_attempt_tier_2_expected_output_mismatch():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {"tier": 1, "included_files": ["status.py"], "exported_symbols": []}
        ],
        "nodes": [
            {"id": "status.py", "tier": 1, "exports": []}
        ]
    }
    job = MockJob(repo_url="https://github.com/psf/requests", repo_name="psf/requests", graph_data=graph_data)
    user_code = "print('Error: 404 Not Found')\n"
    
    result = engine.grade_attempt(job, 1, user_code, "python", graph_data)
    assert result["grading_method"] == "expected_output"
    assert result["passed"] is False
    assert result["status"] == "attempting"
    assert "Expected stdout to match" in result["details"]["diff_summary"]


def test_grade_attempt_tier_3_structural_only_passing():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {
                "tier": 1,
                "included_files": ["parser.py"],
                "exported_symbols": ["parse_tokens", "TokenStream"]
            }
        ],
        "nodes": [
            {
                "id": "parser.py",
                "tier": 1,
                "exports": ["parse_tokens", "TokenStream"]
            }
        ]
    }
    job = MockJob(repo_url="https://github.com/custom/unknown-repo", repo_name="custom/unknown-repo", graph_data=graph_data)
    user_code = """
class TokenStream:
    def __init__(self, text):
        self.text = text

def parse_tokens(stream):
    return [stream.text]

print("Ready")
"""
    result = engine.grade_attempt(job, 1, user_code, "python", graph_data)
    assert result["grading_method"] == "structural_only"
    assert result["passed"] is True
    assert result["status"] == "structurally_verified"
    assert result["verification"]["structurally_verified"] is True


def test_grade_attempt_tier_3_structural_only_missing_symbols():
    engine = GradingEngine()
    graph_data = {
        "milestones": [
            {
                "tier": 1,
                "included_files": ["parser.py"],
                "exported_symbols": ["parse_tokens", "TokenStream"]
            }
        ],
        "nodes": [
            {
                "id": "parser.py",
                "tier": 1,
                "exports": ["parse_tokens", "TokenStream"]
            }
        ]
    }
    job = MockJob(repo_url="https://github.com/custom/unknown-repo", repo_name="custom/unknown-repo", graph_data=graph_data)
    user_code = "def parse_tokens(s): return []"
    
    result = engine.grade_attempt(job, 1, user_code, "python", graph_data)
    assert result["grading_method"] == "structural_only"
    assert result["passed"] is False
    assert result["status"] == "attempting"
    assert len(result["verification"]["missing_symbols"]) > 0


def test_db_persistence_of_grading_method():
    init_db()
    with get_db_session() as db:
        user = db.query(UserModel).filter_by(github_username="grade_test_user").first()
        if not user:
            user = UserModel(github_id=99998888, github_username="grade_test_user", email="grade@test.com")
            db.add(user)
            db.commit()
            db.refresh(user)

        job = AnalysisJobModel(
            user_id=user.id,
            github_url="https://github.com/psf/requests",
            repo_name="psf/requests",
            status="completed",
            run_id="run_grade_test_123"
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        attempt = MilestoneAttemptModel(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=1,
            submitted_code="print('HTTP Adapter initialized: max_retries=3, status=200')",
            status="structurally_verified",
            grading_method="expected_output",
            grading_details_json=json.dumps({"match_mode": "contains", "expected": "status=200"})
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)

        saved_attempt = db.query(MilestoneAttemptModel).filter_by(
            user_id=user.id,
            job_id=job.id,
            milestone_tier=1
        ).first()

        assert saved_attempt is not None
        assert saved_attempt.grading_method == "expected_output"
        details = json.loads(saved_attempt.grading_details_json)
        assert details["expected"] == "status=200"
