import json
import multiprocessing
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, r"d:\Projects\Reverse")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import init_db
from app.models.db import RepoModel, utc_now
from app.orchestration.pipeline import PipelineOrchestrator
from app.orchestration.schema import PipelineProgressEvent
from app.storage.repository import StorageRepository


def worker_with_storage(queue, db_url):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    init_db(engine)
    SessionMaker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    cache_path = Path(r"d:\Projects\Reverse\tests\fixtures\flask_cache.json")
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    flask_contents = cache_data["code_contents"]
    file_paths = list(flask_contents.keys())

    with SessionMaker() as session:
        repo, is_new = StorageRepository.acquire_processing_lock(
            session=session,
            github_url="https://github.com/pallets/flask",
            commit_hash="abc1234",
        )
        session.commit()
        queue.put(("LOCK_ACQUIRED", repo.id, repo.status, is_new))

    def cb(ev: PipelineProgressEvent):
        queue.put((ev.stage.value, ev.progress_pct, ev.message))

    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="pallets/flask",
        file_paths=file_paths,
        file_contents=flask_contents,
        progress_callback=cb,
        enable_rag=True,
    )

    with SessionMaker() as session:
        repo = session.get(RepoModel, repo.id)
        if res.success:
            StorageRepository.save_analysis_result(session, repo, res)
        else:
            StorageRepository.mark_repo_failed(session, repo, res.error or "error")
        session.commit()
    queue.put(("FINISHED", res.success))


def run_empirical_kill_recovery_test():
    print("=" * 80)
    print("EMPIRICAL KILL & DEAD-WORKER LOCK RECOVERY TEST")
    print("=" * 80)

    test_db_path = Path("test_orchestrator_kill_recovery.db")
    if test_db_path.exists():
        test_db_path.unlink()
    db_url = f"sqlite:///{test_db_path.resolve()}"
    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    init_db(test_engine)
    test_sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=worker_with_storage, args=(q, db_url))
    p.start()

    storage_events = []
    while p.is_alive():
        if not q.empty():
            item = q.get()
            storage_events.append(item)
            print(f"[Worker Event] {item}")
            if item[0] == "understanding":
                time.sleep(0.4)
                print(f"\n--> SIMULATING CRASH/KILL: Terminating worker process (PID {p.pid}) mid-layer...")
                p.terminate()
                p.join(timeout=2)
                if p.is_alive():
                    p.kill()
                    p.join()
                break
        time.sleep(0.01)

    print(f"Worker process terminated. Exit code: {p.exitcode}")

    # Check database state left behind
    print("\n--- 1. DATABASE STATE IMMEDIATELY AFTER KILL ---")
    with test_sessionmaker() as session:
        repos = session.query(RepoModel).all()
        for r in repos:
            print(f"Row {r.id}: url={r.github_url}, commit={r.commit_hash}, status='{r.status}', error='{r.error_message}'")

    # Step 2: Immediate Retry (< 15 min lock TTL)
    print("\n--- 2. IMMEDIATE RETRY ATTEMPT (< 15-minute lock TTL) ---")
    with test_sessionmaker() as session:
        repo_immediate, is_new_immediate = StorageRepository.acquire_processing_lock(
            session=session,
            github_url="https://github.com/pallets/flask",
            commit_hash="abc1234",
            lock_timeout_seconds=900,
        )
        print(f"Immediate acquire_processing_lock: is_new_lock={is_new_immediate}, row_id={repo_immediate.id}, status='{repo_immediate.status}'")
        assert is_new_immediate is False, "Immediate retry should be blocked while worker presumed active!"
        print("VERIFIED: Immediate retry correctly blocked (lock is held by in-flight worker).")

    # Step 3: Age lock past 15-minute TTL window (dead worker simulation)
    print("\n--- 3. ADVANCING LOCK AGE PAST TTL (> 900s) ---")
    with test_sessionmaker() as session:
        r = session.query(RepoModel).filter_by(id=1).first()
        r.created_at = utc_now() - timedelta(seconds=910)
        session.commit()
        print(f"Simulated lock age: 910s (exceeds 900s timeout).")

    # Step 4: Retry after TTL window has expired
    print("\n--- 4. RETRY ATTEMPT AFTER LOCK TTL EXPIRATION ---")
    with test_sessionmaker() as session:
        repo_reclaimed, is_new_reclaimed = StorageRepository.acquire_processing_lock(
            session=session,
            github_url="https://github.com/pallets/flask",
            commit_hash="abc1234",
            lock_timeout_seconds=900,
        )
        session.commit()
        print(f"Reclaimed acquire_processing_lock: is_new_lock={is_new_reclaimed}, new_row_id={repo_reclaimed.id}, status='{repo_reclaimed.status}'")
        assert is_new_reclaimed is True, "Retry after TTL should grant new lock!"
        assert repo_reclaimed.id != 1, "New lock should be a fresh DB record!"

        # Inspect old crashed record
        old_r = session.query(RepoModel).filter_by(id=1).first()
        print(f"Crashed Worker Record (ID 1): status='{old_r.status}', error='{old_r.error_message}'")
        assert old_r.status == "failed"
        assert "Dead worker detected" in old_r.error_message

    # Step 5: Execute pipeline to completion on reclaimed lock
    print("\n--- 5. COMPLETING RETRIED RUN ON RECLAIMED LOCK ---")
    cache_path = Path(r"d:\Projects\Reverse\tests\fixtures\flask_cache.json")
    with open(cache_path, "r", encoding="utf-8") as f:
        cache_data = json.load(f)
    flask_contents = cache_data["code_contents"]
    file_paths = list(flask_contents.keys())

    orchestrator = PipelineOrchestrator()
    res = orchestrator.run_pipeline(
        repo_name="pallets/flask",
        file_paths=file_paths,
        file_contents=flask_contents,
        enable_rag=True,
    )
    with test_sessionmaker() as session:
        r_active = session.get(RepoModel, repo_reclaimed.id)
        if res.success:
            StorageRepository.save_analysis_result(session, r_active, res)
        session.commit()

        final_r = session.get(RepoModel, repo_reclaimed.id)
        print(f"Final Reclaimed Record (ID {final_r.id}): status='{final_r.status}', success={res.success}, milestones={len(res.report.milestones)}")
        assert final_r.status == "complete"

    print("\n" + "=" * 80)
    print("SUCCESS: Dead worker lock reclamation and recovery fully verified!")
    print("=" * 80)

    test_engine.dispose()
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    run_empirical_kill_recovery_test()

