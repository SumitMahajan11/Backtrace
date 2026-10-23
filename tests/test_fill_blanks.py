"""Test for 'Fill the gaps' endpoint verification (Prompt Part A).

Tests that posting a wrong answer returns passed=false and posting a correct
answer returns passed=true, and prints the raw JSON response.
"""

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.main import app
from app.models.db import Base, UserModel
from app.security.auth import create_access_token
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository


SAMPLE_SOURCE = '''import os
from typing import List

class DataAggregator:
    def __init__(self, prefix: str):
        self.prefix = prefix

    def aggregate(self, items: List[int]) -> int:
        total = 0
        for item in items:
            total += item
        return total
'''


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


def test_fill_blanks_wrong_and_correct_answers(client, create_user, test_db):
    SessionLocal, _ = test_db
    user = create_user(github_id=40401, username="fill_tester")
    token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)
    client.cookies.set("access_token", token)

    report_md = """# Architectural Report
## 3. Step-by-Step Architectural Milestones

### Milestone 0: Core Aggregator
**[HIGH CONFIDENCE]** -- *Aggregator*
**Overview:** Core data aggregation service.
**Included Files:**
- `app/aggregator.py`
"""

    with SessionLocal() as session:
        job = AnalysisJobRepository.create_job(
            session=session,
            user_id=user.id,
            repo_url="https://github.com/example-org/aggregator-demo",
            status="completed",
        )
        AnalysisJobRepository.update_job_status(
            session=session,
            job_id=job.id,
            status="completed",
            report_markdown=report_md,
            graph_data={
                "nodes": [
                    {
                        "id": "app/aggregator.py",
                        "path": "app/aggregator.py",
                        "tier": 0,
                        "source_code": SAMPLE_SOURCE,
                    },
                ],
                "edges": [],
            },
        )
        job_id = job.id

    # 1. Post a WRONG answer (blanks not implemented, left as pass)
    wrong_code = '''import os
from typing import List

class DataAggregator:
    def __init__(self, prefix: str):
        pass

    def aggregate(self, items: List[int]) -> int:
        pass
'''
    wrong_payload = {
        "submitted_code": wrong_code,
        "mode": "fill",
        "target_file": "app/aggregator.py",
    }
    resp_wrong = client.post(f"/api/attempts/{job_id}/0", json=wrong_payload)
    assert resp_wrong.status_code == 200, f"Expected 200 but got {resp_wrong.status_code}: {resp_wrong.text}"
    wrong_json = resp_wrong.json()

    print("\n=== RAW RESPONSE: WRONG ANSWER ===")
    print(json.dumps(wrong_json, indent=2))
    assert wrong_json.get("passed") is False, f"Expected passed=false, got {wrong_json.get('passed')}"

    # 2. Post a CORRECT answer (real functional implementation)
    correct_payload = {
        "submitted_code": SAMPLE_SOURCE,
        "mode": "fill",
        "target_file": "app/aggregator.py",
    }
    resp_correct = client.post(f"/api/attempts/{job_id}/0", json=correct_payload)
    assert resp_correct.status_code == 200, f"Expected 200 but got {resp_correct.status_code}: {resp_correct.text}"
    correct_json = resp_correct.json()

    print("\n=== RAW RESPONSE: CORRECT ANSWER ===")
    print(json.dumps(correct_json, indent=2))
    assert correct_json.get("passed") is True, f"Expected passed=true, got {correct_json.get('passed')}"
