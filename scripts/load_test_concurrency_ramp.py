"""Comprehensive Multi-Concurrency Load Testing Script (Prompt 22).

Executes a concurrency ramp (10 -> 25 -> 50 -> 100 concurrent users) against the
PostgreSQL-backed application persistence layer and Piston sandbox execution stack.
Measures latency distribution, throughput, error rate, and connection pool behavior.
"""

import concurrent.futures
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from fastapi.testclient import TestClient

# Ensure DATABASE_URL points to PostgreSQL
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/backtrace",
)

from app.db.session import SessionLocal, engine
from app.main import app
from app.models.db import AnalysisJobModel, UserModel
from app.security.auth import create_access_token
from app.security.rate_limiter import execution_rate_limiter
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.user_repository import UserRepository


def setup_load_test_users(num_users: int = 100) -> List[Dict[str, Any]]:
    """Ensures 100 distinct authenticated test users and jobs exist in PostgreSQL."""
    print(f"[*] Preparing {num_users} test users and analysis jobs in PostgreSQL...")
    user_data = []
    with SessionLocal() as session:
        for uid in range(1, num_users + 1):
            github_id = 80000 + uid
            user = UserRepository.get_user_by_github_id(session, github_id)
            if not user:
                user = UserRepository.upsert_github_user(
                    session=session,
                    github_id=github_id,
                    github_username=f"load_user_{uid}",
                    email=f"load_{uid}@loadtest.local",
                )
                session.commit()
                session.refresh(user)

            job = session.query(AnalysisJobModel).filter_by(
                user_id=user.id,
                github_url=f"https://github.com/loadtest/repo_{uid}",
            ).first()
            if not job:
                job = AnalysisJobRepository.create_job(
                    session=session,
                    user_id=user.id,
                    github_url=f"https://github.com/loadtest/repo_{uid}",
                    repo_name=f"repo_{uid}",
                )
                job.graph_output_json = json.dumps({
                    "milestones": [
                        {"tier": 1, "name": "Milestone 1", "test_code": "assert True"},
                        {"tier": 3, "name": "Milestone 3", "expected_symbols": ["load_func"]}
                    ],
                    "nodes": [
                        {"id": "main.py", "type": "module", "tier": 3, "exports": ["load_func"]}
                    ]
                })
                session.commit()
                session.refresh(job)

            token = create_access_token(
                user_id=user.id,
                github_id=user.github_id,
                github_username=user.github_username,
            )
            user_data.append({
                "user_id": user.id,
                "github_id": user.github_id,
                "username": user.github_username,
                "job_id": job.id,
                "token": token,
            })
    print(f"[+] Successfully verified {len(user_data)} authenticated load test fixtures.")
    return user_data


def simulate_user_session(user_info: Dict[str, Any], ops_per_user: int = 2) -> List[Dict[str, Any]]:
    """Simulates a user issuing execution and submission requests."""
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {user_info['token']}"}
    job_id = user_info["job_id"]
    uid = user_info["user_id"]
    results = []

    for op_idx in range(ops_per_user):
        is_run = (op_idx % 2 == 0)
        t0 = time.perf_counter()
        
        # Check pool metrics at request dispatch
        try:
            pool_out = engine.pool.checkedout()
            pool_in = engine.pool.checkedin()
            pool_over = engine.pool.overflow()
        except Exception:
            pool_out, pool_in, pool_over = -1, -1, -1

        status_code = 0
        error_msg = None

        try:
            if is_run:
                resp = client.post(
                    f"/api/attempts/{job_id}/1/run",
                    headers=headers,
                    json={"submitted_code": f"print('Load test User {uid} Run {op_idx}')", "language": "python"},
                )
            else:
                resp = client.post(
                    f"/api/attempts/{job_id}/3",
                    headers=headers,
                    json={"submitted_code": "def load_func():\n    return True\n", "language": "python"},
                )
            status_code = resp.status_code
            if status_code not in (200, 429):
                error_msg = f"HTTP {status_code}: {resp.text[:100]}"
        except Exception as exc:
            status_code = 500
            error_msg = str(exc)

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        results.append({
            "user_id": uid,
            "op_idx": op_idx + 1,
            "op_type": "RUN" if is_run else "SUBMIT",
            "latency_ms": round(elapsed_ms, 2),
            "status_code": status_code,
            "error": error_msg,
            "pool_out": pool_out,
            "pool_in": pool_in,
            "pool_over": pool_over,
        })
        time.sleep(random.uniform(0.01, 0.03))

    return results


def run_concurrency_tier(concurrency: int, all_users: List[Dict[str, Any]], ops_per_user: int = 2) -> Dict[str, Any]:
    """Runs load test at a specific concurrency level and returns summarized metrics."""
    selected_users = all_users[:concurrency]
    # Reset rate limiters before benchmark tier so all users start with clean token capacity
    execution_rate_limiter.reset_all()

    print(f"\n>>> Running Concurrency Tier: {concurrency} Concurrent Users ({concurrency * ops_per_user} total requests)...")
    t_start = time.perf_counter()
    tier_logs = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(simulate_user_session, user, ops_per_user) for user in selected_users]
        for future in concurrent.futures.as_completed(futures):
            tier_logs.extend(future.result())

    total_time = time.perf_counter() - t_start
    total_reqs = len(tier_logs)

    latencies = [l["latency_ms"] for l in tier_logs]
    latencies.sort()

    successes = sum(1 for l in tier_logs if l["status_code"] in (200, 429))
    http_200s = sum(1 for l in tier_logs if l["status_code"] == 200)
    http_429s = sum(1 for l in tier_logs if l["status_code"] == 429)
    errors = sum(1 for l in tier_logs if l["status_code"] >= 500 or l["status_code"] not in (200, 429))

    max_pool_out = max((l["pool_out"] for l in tier_logs), default=0)
    max_pool_over = max((l["pool_over"] for l in tier_logs), default=0)

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p50_lat = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    p99_lat = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)] if latencies else 0.0
    max_lat = latencies[-1] if latencies else 0.0
    throughput = total_reqs / total_time if total_time > 0 else 0.0

    return {
        "concurrency": concurrency,
        "total_reqs": total_reqs,
        "total_time_s": round(total_time, 3),
        "throughput_rps": round(throughput, 2),
        "success_rate_pct": round((successes / total_reqs) * 100.0, 2),
        "http_200_count": http_200s,
        "http_429_count": http_429s,
        "error_count": errors,
        "min_ms": latencies[0] if latencies else 0.0,
        "avg_ms": round(avg_lat, 2),
        "p50_ms": round(p50_lat, 2),
        "p95_ms": round(p95_lat, 2),
        "p99_ms": round(p99_lat, 2),
        "max_ms": round(max_lat, 2),
        "max_pool_out": max_pool_out,
        "max_pool_over": max_pool_over,
        "sample_logs": tier_logs[:6],
    }


def execute_full_load_test():
    print("=" * 95)
    print("PROMPT 22: MULTI-CONCURRENCY LOAD TEST & RATE LIMIT RAMP (10 -> 25 -> 50 -> 100)")
    print(f"Target DB: {os.environ.get('DATABASE_URL')}")
    print(f"PostgreSQL Pool: size={engine.pool.size()}, max_overflow={engine.pool._max_overflow}, timeout={engine.pool._timeout}")
    print("=" * 95)

    from app.services.piston_health import piston_health_monitor
    piston_health_monitor.check_health_sync()
    print(f"Piston Health Status: {piston_health_monitor.get_status()}")

    all_users = setup_load_test_users(100)
    tiers = [10, 25, 50, 100]
    tier_results = []

    for c in tiers:
        res = run_concurrency_tier(concurrency=c, all_users=all_users, ops_per_user=2)
        tier_results.append(res)

    print("\n" + "=" * 95)
    print("CONCURRENCY RAMP DEGRADATION MATRIX & PERFORMANCE CURVE")
    print("=" * 95)
    header = (
        f"{'Concurrency':<12} | {'Requests':<8} | {'Throughput':<12} | "
        f"{'P50 Latency':<12} | {'P95 Latency':<12} | {'P99 Latency':<12} | "
        f"{'Max Latency':<12} | {'Success Rate':<12} | {'Pool (Out/Over)'}"
    )
    print(header)
    print("-" * len(header))
    for r in tier_results:
        pool_str = f"{r['max_pool_out']}/{r['max_pool_over']}"
        print(
            f"{r['concurrency']:<12} | "
            f"{r['total_reqs']:<8} | "
            f"{r['throughput_rps']:>7.2f} req/s | "
            f"{r['p50_ms']:>8.2f} ms | "
            f"{r['p95_ms']:>8.2f} ms | "
            f"{r['p99_ms']:>8.2f} ms | "
            f"{r['max_ms']:>8.2f} ms | "
            f"{r['success_rate_pct']:>10.2f}% | "
            f"{pool_str}"
        )
    print("=" * 95)

    print("\n--- SAMPLE RAW PER-REQUEST LOGS (From 100-User Tier) ---")
    tier_100 = tier_results[-1]
    for log in tier_100["sample_logs"]:
        print(f"User {log['user_id']:<3} | Op #{log['op_idx']} ({log['op_type']:<6}) | Latency: {log['latency_ms']:>6.2f} ms | Status: {log['status_code']} | Pool: {log['pool_out']}/{log['pool_in']}/{log['pool_over']}")


if __name__ == "__main__":
    execute_full_load_test()
