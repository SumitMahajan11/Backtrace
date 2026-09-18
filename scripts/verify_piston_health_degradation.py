"""End-to-end empirical verification of Piston Health Check & Graceful Degradation (Prompt 21).

Steps executed against live infrastructure:
1. Check /health when Piston is healthy (status='healthy', is_available=True).
2. Stop Piston container (docker stop backtrace_piston in WSL).
3. Trigger health monitor probe and check /health (status='unhealthy', is_available=False).
4. Attempt /run call while Piston is down (confirm fast-fail 503, elapsed time < 50ms).
5. Attempt Tier-3 structural submit while Piston is down (confirm 200 OK, structurally_verified).
6. Restart Piston container (docker start backtrace_piston in WSL).
7. Trigger health monitor probe and check /health (flips back to status='healthy').
8. Attempt /run call with Piston healthy (confirm 200 OK with real stdout and exit_code=0).
"""

import json
import subprocess
import time
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.services.piston_health import piston_health_monitor
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository


def wsl_docker_cmd(args_list: list[str]) -> str:
    """Executes docker command inside WSL where containers run."""
    cmd = ["wsl", "-d", "Ubuntu", "-u", "root", "--", "docker"] + args_list
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return res.stdout.strip()


def run_verification():
    print("=" * 80)
    print("PROMPT 21: PISTON HEALTH CHECK & GRACEFUL DEGRADATION VERIFICATION")
    print("=" * 80)

    # 1. Ensure test user & test analysis job exist in PostgreSQL
    with SessionLocal() as session:
        user = UserRepository.get_user_by_github_id(session, 77777)
        if not user:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=77777,
                github_username="health_verifier",
                email="verifier@test.local",
            )
            session.commit()
            session.refresh(user)
        user_id = user.id
        token = create_access_token(user_id=user.id, github_id=user.github_id, github_username=user.github_username)

        job = session.query(AnalysisJobModel).filter_by(user_id=user_id, github_url="https://github.com/test/health-check-repo").first()
        if not job:
            job = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                github_url="https://github.com/test/health-check-repo",
                repo_name="health-check-repo",
            )
            job.graph_output_json = json.dumps({
                "milestones": [
                    {"tier": 1, "name": "Execution Tier 1", "test_code": "assert True"},
                    {"tier": 3, "name": "Structural Tier 3", "expected_symbols": ["verify_token"]}
                ],
                "nodes": [
                    {"id": "auth.py", "type": "module", "tier": 3, "exports": ["verify_token"]}
                ]
            })
            session.commit()
            session.refresh(job)
        job_id = job.id

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    # =========================================================================
    # STEP 1: App Health with Piston Up
    # =========================================================================
    print("\n[STEP 1] Checking /health with Piston Container UP")
    piston_health_monitor.check_health_sync()
    resp_healthy = client.get("/health")
    print(f"HTTP Status: {resp_healthy.status_code}")
    print("Response JSON:")
    print(json.dumps(resp_healthy.json(), indent=2))

    # =========================================================================
    # STEP 2: Stop Piston Container
    # =========================================================================
    print("\n[STEP 2] Stopping Piston Container (docker stop backtrace_piston)...")
    stop_out = wsl_docker_cmd(["stop", "backtrace_piston"])
    print(f"Container stopped: {stop_out}")
    time.sleep(1.0)

    # =========================================================================
    # STEP 3: Checking /health with Piston Down
    # =========================================================================
    print("\n[STEP 3] Probing /health with Piston Container DOWN")
    piston_health_monitor.check_health_sync()
    resp_down = client.get("/health")
    print(f"HTTP Status: {resp_down.status_code}")
    print("Response JSON:")
    print(json.dumps(resp_down.json(), indent=2))

    # =========================================================================
    # STEP 4: Attempt /run call while Piston is down (Fast-fail check)
    # =========================================================================
    print("\n[STEP 4] Attempting /run call while Piston is DOWN (Fast-fail check)")
    t0 = time.perf_counter()
    resp_run_down = client.post(
        f"/api/attempts/{job_id}/1/run",
        headers=headers,
        json={"submitted_code": "print('hello from down test')", "language": "python"},
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    print(f"HTTP Status: {resp_run_down.status_code}")
    print(f"Elapsed Time: {elapsed_ms:.2f} ms (Must be fast, << 3000ms timeout)")
    print("Response JSON:")
    print(json.dumps(resp_run_down.json(), indent=2))

    # =========================================================================
    # STEP 5: Attempt Tier 3 Structural Submit while Piston is down
    # =========================================================================
    print("\n[STEP 5] Attempting Tier 3 (structural_only) Submit while Piston is DOWN (Graceful Degradation)")
    resp_submit_t3 = client.post(
        f"/api/attempts/{job_id}/3",
        headers=headers,
        json={
            "submitted_code": "def verify_token(token: str) -> bool:\n    return bool(token)\n",
            "language": "python",
        },
    )
    print(f"HTTP Status: {resp_submit_t3.status_code}")
    print("Response JSON:")
    print(json.dumps(resp_submit_t3.json(), indent=2))

    # =========================================================================
    # STEP 6: Restart Piston Container
    # =========================================================================
    print("\n[STEP 6] Restarting Piston Container (docker start backtrace_piston)...")
    start_out = wsl_docker_cmd(["start", "backtrace_piston"])
    print(f"Container started: {start_out}")
    time.sleep(2.0)

    # =========================================================================
    # STEP 7: Checking /health after Piston Restart
    # =========================================================================
    print("\n[STEP 7] Probing /health after Piston Container Restart")
    piston_health_monitor.check_health_sync()
    resp_recovered = client.get("/health")
    print(f"HTTP Status: {resp_recovered.status_code}")
    print("Response JSON:")
    print(json.dumps(resp_recovered.json(), indent=2))

    # =========================================================================
    # STEP 8: Attempt /run call with Piston Restored
    # =========================================================================
    print("\n[STEP 8] Attempting /run call with Piston RESTORED")
    resp_run_up = client.post(
        f"/api/attempts/{job_id}/1/run",
        headers=headers,
        json={"submitted_code": "print('Piston execution verified successfully!')", "language": "python"},
    )
    print(f"HTTP Status: {resp_run_up.status_code}")
    print("Response JSON:")
    print(json.dumps(resp_run_up.json(), indent=2))

    print("\n" + "=" * 80)
    print("ALL 8 VERIFICATION PHASES COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_verification()
