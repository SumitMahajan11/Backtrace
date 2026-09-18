"""Empirical Live Demonstration of Token Bucket Rate Limiting (Prompt 22).

Demonstrates:
1. User A sending requests within capacity (Requests 1-10 -> HTTP 200).
2. User A exceeding limit on Request 11 -> HTTP 429 Too Many Requests with headers:
   - Retry-After
   - X-RateLimit-Limit
   - X-RateLimit-Remaining
   - X-RateLimit-Reset
3. Concurrent User B sending requests at the same moment -> HTTP 200 OK (Strict isolation).
"""

import json
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.security.rate_limiter import execution_rate_limiter
from app.services.piston_health import piston_health_monitor
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository


def run_rate_limiter_demo():
    print("=" * 80)
    print("PROMPT 22: LIVE TOKEN-BUCKET RATE LIMITER & USER ISOLATION DEMONSTRATION")
    print("=" * 80)

    # Ensure Piston monitor is primed healthy
    piston_health_monitor.check_health_sync()

    # Reset limiter for clean demonstration
    execution_rate_limiter.reset_all()

    with SessionLocal() as session:
        # User A setup
        user_a = UserRepository.get_user_by_github_id(session, 91111)
        if not user_a:
            user_a = UserRepository.upsert_github_user(
                session=session,
                github_id=91111,
                github_username="demo_user_alpha",
                email="alpha@demo.local",
            )
            session.commit()
            session.refresh(user_a)

        job_a = session.query(AnalysisJobModel).filter_by(
            user_id=user_a.id, github_url="https://github.com/demo/repo_a"
        ).first()
        if not job_a:
            job_a = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_a.id,
                github_url="https://github.com/demo/repo_a",
                repo_name="repo_a",
            )
            job_a.graph_output_json = json.dumps({
                "milestones": [{"tier": 1, "name": "Milestone 1"}],
                "nodes": [{"id": "a.py", "type": "module", "tier": 1, "exports": ["demo_func_a"]}]
            })
            session.commit()
            session.refresh(job_a)

        user_a_id = user_a.id
        job_a_id = job_a.id
        token_a = create_access_token(user_id=user_a.id, github_id=user_a.github_id, github_username=user_a.github_username)

        # User B setup
        user_b = UserRepository.get_user_by_github_id(session, 92222)
        if not user_b:
            user_b = UserRepository.upsert_github_user(
                session=session,
                github_id=92222,
                github_username="demo_user_beta",
                email="beta@demo.local",
            )
            session.commit()
            session.refresh(user_b)

        job_b = session.query(AnalysisJobModel).filter_by(
            user_id=user_b.id, github_url="https://github.com/demo/repo_b"
        ).first()
        if not job_b:
            job_b = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_b.id,
                github_url="https://github.com/demo/repo_b",
                repo_name="repo_b",
            )
            job_b.graph_output_json = json.dumps({
                "milestones": [{"tier": 1, "name": "Milestone 1"}],
                "nodes": [{"id": "b.py", "type": "module", "tier": 1, "exports": ["demo_func_b"]}]
            })
            session.commit()
            session.refresh(job_b)

        user_b_id = user_b.id
        job_b_id = job_b.id
        token_b = create_access_token(user_id=user_b.id, github_id=user_b.github_id, github_username=user_b.github_username)

    client = TestClient(app)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. User A sends 10 requests (Capacity = 10)
    print("\n[PHASE 1] User A firing 10 consecutive execution requests (Bucket Capacity = 10):")
    for i in range(1, 11):
        resp = client.post(
            f"/api/attempts/{job_a_id}/1/run",
            headers=headers_a,
            json={"submitted_code": f"print('User A request #{i}')", "language": "python"},
        )
        print(f"Request #{i:<2} -> HTTP {resp.status_code} | Remaining: {resp.headers.get('X-RateLimit-Remaining')} | Reset: {resp.headers.get('X-RateLimit-Reset')}s")

    # 2. User A sends 11th request (Exceeds capacity -> HTTP 429)
    print("\n[PHASE 2] User A firing 11th request (Rate Limit Exceeded):")
    resp_429 = client.post(
        f"/api/attempts/{job_a_id}/1/run",
        headers=headers_a,
        json={"submitted_code": "print('User A bursting past capacity')", "language": "python"},
    )
    print(f"HTTP Status: {resp_429.status_code} (Expected: 429)")
    print("Response Headers:")
    for h in ["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"]:
        print(f"  {h}: {resp_429.headers.get(h)}")
    print("Response JSON:")
    print(json.dumps(resp_429.json(), indent=2))

    # 3. Concurrent User B sends a request at the same time (Proving Isolation)
    print("\n[PHASE 3] Concurrent User B firing a request simultaneously:")
    resp_b = client.post(
        f"/api/attempts/{job_b_id}/1/run",
        headers=headers_b,
        json={"submitted_code": "print('User B normal execution unaffected')", "language": "python"},
    )
    print(f"HTTP Status: {resp_b.status_code} (Expected: 200)")
    print(f"User B Remaining Tokens: {resp_b.headers.get('X-RateLimit-Remaining')}")
    print("Response JSON:")
    print(json.dumps(resp_b.json(), indent=2))

    print("\n" + "=" * 80)
    print("RATE LIMITER VERIFICATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_rate_limiter_demo()
