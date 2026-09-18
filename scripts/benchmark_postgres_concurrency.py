"""Concurrency benchmark for PostgreSQL connection pool verification under load.
Simulates 8 concurrent workers executing Milestone Run and Submit operations.
Measures per-request latency, HTTP/DB status, and connection pool utilization.
"""

import concurrent.futures
import json
import os
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

# Ensure DATABASE_URL is set to PostgreSQL
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/backtrace",
)

from app.db.session import SessionLocal, engine
from app.models.db import AnalysisJobModel, MilestoneAttemptModel, UserModel
from app.storage.analysis_job_repository import AnalysisJobRepository
from app.storage.milestone_attempt_repository import MilestoneAttemptRepository
from app.storage.user_repository import UserRepository


def worker_task(worker_id: int, num_operations: int = 5) -> List[Dict[str, Any]]:
    logs = []
    
    # Each worker simulates a user performing runs and submits
    with SessionLocal() as session:
        # Get or create worker user
        user = UserRepository.get_user_by_github_id(session, 90000 + worker_id)
        if not user:
            user = UserRepository.upsert_github_user(
                session=session,
                github_id=90000 + worker_id,
                github_username=f"benchmark_worker_{worker_id}",
                email=f"worker_{worker_id}@benchmark.local",
                avatar_url="https://example.com/avatar.png",
            )
            session.commit()
            session.refresh(user)
        user_id = user.id

        # Get or create worker job
        job = session.query(AnalysisJobModel).filter_by(user_id=user_id, github_url=f"https://github.com/bench/repo_{worker_id}").first()
        if not job:
            job = AnalysisJobRepository.create_job(
                session=session,
                user_id=user_id,
                github_url=f"https://github.com/bench/repo_{worker_id}",
                repo_name=f"repo_{worker_id}",
            )
            session.commit()
            session.refresh(job)
        job_id = job.id

    # Execute operations
    operations = ["RUN", "SUBMIT"]
    milestone_tiers = [1, 2, 3, 4]

    for op_idx in range(num_operations):
        op_type = operations[op_idx % len(operations)]
        tier = milestone_tiers[op_idx % len(milestone_tiers)]
        
        start_time = time.perf_counter()
        req_timestamp = datetime.now(timezone.utc).isoformat()
        
        status = "SUCCESS"
        error_msg = None
        
        try:
            with SessionLocal() as session:
                # Pool metrics at operation time
                pool_checkedout = engine.pool.checkedout()
                pool_checkedin = engine.pool.checkedin()
                pool_overflow = engine.pool.overflow()
                
                if op_type == "RUN":
                    # Simulate Milestone Run: update last_run_* and grading_method
                    attempt = MilestoneAttemptRepository.save_or_update_attempt(
                        session=session,
                        user_id=user_id,
                        job_id=job_id,
                        milestone_tier=tier,
                        submitted_code=f"def test_worker_{worker_id}_step_{op_idx}():\n    assert 1 == 1\n",
                        status="in_progress",
                        grading_method="piston",
                        grading_details_json=json.dumps({
                            "stdout": f"Worker {worker_id} Run passed",
                            "stderr": "",
                            "exit_code": 0,
                            "execution_time_ms": round(random.uniform(40, 120), 2),
                            "tests_passed": 3,
                            "tests_total": 3,
                        }),
                        last_run_stdout=f"Worker {worker_id} test output OK",
                        last_run_stderr="",
                        last_run_exit_code=0,
                        last_run_at=datetime.now(timezone.utc),
                    )
                else:  # SUBMIT
                    # Simulate Milestone Submit: grade and mark passed
                    attempt = MilestoneAttemptRepository.save_or_update_attempt(
                        session=session,
                        user_id=user_id,
                        job_id=job_id,
                        milestone_tier=tier,
                        submitted_code=f"def solution_worker_{worker_id}_step_{op_idx}():\n    return 'verified'\n",
                        status="passed",
                        grading_method="piston",
                        grading_details_json=json.dumps({
                            "stdout": f"Worker {worker_id} Submit passed 5/5 assertions",
                            "stderr": "",
                            "exit_code": 0,
                            "execution_time_ms": round(random.uniform(60, 180), 2),
                            "score": 100.0,
                        }),
                        last_run_stdout=f"All 5 tests passed for tier {tier}",
                        last_run_stderr="",
                        last_run_exit_code=0,
                        last_run_at=datetime.now(timezone.utc),
                        hint_level_revealed=1,
                    )
                session.commit()
                
        except Exception as exc:
            status = "FAILED"
            error_msg = str(exc)
            pool_checkedout = -1
            pool_checkedin = -1
            pool_overflow = -1
            
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        
        log_entry = {
            "timestamp": req_timestamp,
            "worker_id": worker_id,
            "op_idx": op_idx + 1,
            "operation": op_type,
            "tier": tier,
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "error": error_msg,
            "pool_checkedout": pool_checkedout,
            "pool_checkedin": pool_checkedin,
            "pool_overflow": pool_overflow,
        }
        logs.append(log_entry)
        
        # Small jitter between operations (10-30ms)
        time.sleep(random.uniform(0.01, 0.03))

    return logs


def run_benchmark(num_workers: int = 8, ops_per_worker: int = 5):
    print("=" * 95)
    print(f"POSTGRESQL CONCURRENCY BENCHMARK ({num_workers} Concurrent Workers, {ops_per_worker} ops/worker)")
    print(f"Target DB: {os.environ.get('DATABASE_URL')}")
    print(f"Connection Pool: size={engine.pool.size()}, max_overflow={engine.pool._max_overflow}, timeout={engine.pool._timeout}")
    print("=" * 95)
    
    start_bench = time.perf_counter()
    all_logs = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_task, worker_id, ops_per_worker) for worker_id in range(1, num_workers + 1)]
        for future in concurrent.futures.as_completed(futures):
            all_logs.extend(future.result())
            
    total_duration = time.perf_counter() - start_bench
    
    # Sort logs chronologically
    all_logs.sort(key=lambda x: (x["timestamp"], x["worker_id"]))
    
    print("\n--- RAW PER-REQUEST LOGS ---")
    header = f"{'Timestamp':<27} | {'Worker':<7} | {'Op #':<5} | {'Type':<6} | {'Tier':<5} | {'Latency':<9} | {'Status':<7} | {'Pool (Out/In/Over)'}"
    print(header)
    print("-" * len(header))
    for log in all_logs:
        pool_str = f"{log['pool_checkedout']}/{log['pool_checkedin']}/{log['pool_overflow']}"
        print(
            f"{log['timestamp']:<27} | "
            f"W-{log['worker_id']:<5} | "
            f"#{log['op_idx']:<4} | "
            f"{log['operation']:<6} | "
            f"T-{log['tier']:<3} | "
            f"{log['duration_ms']:>6.2f} ms | "
            f"{log['status']:<7} | "
            f"{pool_str}"
        )
        
    # Statistical analysis
    latencies = [log["duration_ms"] for log in all_logs]
    successes = sum(1 for log in all_logs if log["status"] == "SUCCESS")
    total_ops = len(all_logs)
    success_rate = (successes / total_ops) * 100.0 if total_ops > 0 else 0.0
    
    latencies.sort()
    min_lat = latencies[0] if latencies else 0.0
    max_lat = latencies[-1] if latencies else 0.0
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p50_lat = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p95_lat = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    p99_lat = latencies[min(int(len(latencies) * 0.99), len(latencies) - 1)] if latencies else 0.0
    
    print("\n" + "=" * 95)
    print("CONCURRENCY BENCHMARK SUMMARY")
    print("=" * 95)
    print(f"Total Requests Executed : {total_ops}")
    print(f"Concurrent Workers      : {num_workers}")
    print(f"Wall-Clock Time         : {total_duration:.3f} s")
    print(f"Throughput              : {total_ops / total_duration:.2f} req/s")
    print(f"Success Rate            : {success_rate:.2f}% ({successes}/{total_ops})")
    print(f"Latency Min             : {min_lat:.2f} ms")
    print(f"Latency Avg             : {avg_lat:.2f} ms")
    print(f"Latency P50 (Median)    : {p50_lat:.2f} ms")
    print(f"Latency P95             : {p95_lat:.2f} ms")
    print(f"Latency P99             : {p99_lat:.2f} ms")
    print(f"Latency Max             : {max_lat:.2f} ms")
    print("=" * 95)


if __name__ == "__main__":
    run_benchmark(num_workers=8, ops_per_worker=5)
