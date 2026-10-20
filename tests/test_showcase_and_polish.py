"""Comprehensive tests for Round 7: Public View-Only Showcase, Seed Scripts, and Polishes."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import (
    AnalysisJobModel,
    AnalysisResultModel,
    IngestionResultModel,
    RepoModel,
    UserModel,
    utc_now,
)
from app.security.auth import create_access_token
from app.storage.repository import StorageRepository
from scripts.export_showcase import (
    count_secret_matches,
    export_showcase_job,
    scan_payload_for_secrets,
)
from scripts.seed_showcase import seed_showcase_file


SAMPLE_REPORT_MD = """# Architectural Reverse-Engineering Report: `expressjs/express`

*Synthesized at: 2026-10-20 12:00:00 UTC*
<!-- narration_source: template -->

## 1. Executive Summary & Core Architectural Invariants
- **Primary Language**: `JavaScript`
- **Total Analyzed Files**: `3`
- **Domain Categories**: `2`
- **Entry Point Files**: `index.js`
- **Cyclic Core Components**: `0`
- **Isolated / Support Files**: `0`

| Domain Category | File Count | Percentage |
| :--- | :--- | :--- |
| `core` | 2 | 66.7% |
| `router` | 1 | 33.3% |

## 2. Build Order & Confidence Scoring
Sequence reasoning notes here.

## 3. Step-by-Step Architectural Milestones

### Milestone 1: Core Initialization (Tier 1)
**[HIGH CONFIDENCE]** -- *Bootstrap core runtime*

**Overview:**
Initialize core framework structures.

**Domain Composition:**
Core initialization logic.

**Included Files (1):**
- `lib/express.js`

**Key Exported Symbols:** `createApplication, express`

**Deep-Dive Semantic Citations:**
- Primary application factory

**Pedagogical Notes:**
- Foundational layer
"""


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


def create_user_helper(session, github_id: int, username: str, email: str) -> UserModel:
    user = UserModel(
        github_id=github_id,
        github_username=username,
        email=email,
        avatar_url=f"https://avatars.example.com/{username}",
        is_admin=False,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_job_helper(
    session,
    user_id: int,
    repo_name: str = "express",
    is_showcase: bool = False,
    status: str = "completed",
    run_id: str = "run_test_1",
) -> AnalysisJobModel:
    job = AnalysisJobModel(
        user_id=user_id,
        repo_name=repo_name,
        github_url=f"https://github.com/expressjs/{repo_name}",
        commit_ref="main",
        resolved_sha="abc123456789",
        status=status,
        run_id=run_id,
        markdown_output=SAMPLE_REPORT_MD,
        graph_output_json=json.dumps({"nodes": [{"id": "lib/express.js", "label": "express.js", "tier": 1}], "edges": []}),
        quiz_output_json=json.dumps({"questions": [{"question": "What is Tier 1?", "options": ["A", "B"], "correct_index": 0, "tier": 1}]}),
        is_showcase=is_showcase,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# -------------------------------------------------------------------------
# Test (a): Logged-out request to showcase report returns 200 with no attempt controls
# -------------------------------------------------------------------------
def test_showcase_report_logged_out_returns_200_no_attempt_controls(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 1001, "showcase_dev", "dev@showcase.internal")
        job = create_job_helper(session, owner.id, "showcase-repo", is_showcase=True)
        job_id = job.id

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    html = resp.text

    # Banner must be present
    assert "View-only showcase" in html
    assert "showcase-banner" in html

    # Attempt, run, hint, reveal, review controls must be absent
    assert 'onclick="switchMilestoneMode(' not in html
    assert 'class="milestone-mode-switcher"' not in html
    assert 'id="workspace-guess-' not in html
    assert 'id="workspace-fill-' not in html
    assert 'btn-run-' not in html
    assert 'btn-submit-' not in html
    assert 'btn-hint-' not in html
    assert 'btn-reveal-' not in html
    assert 'btn-review-' not in html
    assert "runMilestoneCode(" not in html
    assert "submitMilestoneCode(" not in html
    assert "confirmAndFetchHint(" not in html
    assert "confirmAndRevealImplementation(" not in html
    assert "markMilestoneAsReviewed(" not in html
    import re
    assert not re.search(r"<script[^>]*codemirror", html, re.IGNORECASE)
    assert not re.search(r"<link[^>]*codemirror", html, re.IGNORECASE)
    assert "codemirror.min.js" not in html.lower()
    assert "codemirror.min.css" not in html.lower()


# -------------------------------------------------------------------------
# Test (b): Logged-out request to non-showcase report redirects
# -------------------------------------------------------------------------
def test_non_showcase_report_logged_out_redirects(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 1002, "private_dev", "private@internal.net")
        job = create_job_helper(session, owner.id, "private-repo", is_showcase=False)
        job_id = job.id

    resp = client.get(f"/report/{job_id}", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


# -------------------------------------------------------------------------
# Test (c): Non-owner request to non-showcase report returns 403
# -------------------------------------------------------------------------
def test_non_owner_request_to_non_showcase_report_returns_403(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 1003, "real_owner", "owner@internal.net")
        stranger = create_user_helper(session, 1004, "stranger_user", "stranger@internal.net")
        job = create_job_helper(session, owner.id, "secret-repo", is_showcase=False)
        job_id = job.id
        stranger_id = stranger.id
        stranger_github_id = stranger.github_id
        stranger_username = stranger.github_username

    token = create_access_token(
        user_id=stranger_id,
        github_id=stranger_github_id,
        github_username=stranger_username,
    )
    client.cookies.set("access_token", token)

    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 403
    assert "Access forbidden" in resp.text


# -------------------------------------------------------------------------
# Test (d): Logged out, attempts and points APIs return 401 for a showcase job
# -------------------------------------------------------------------------
def test_logged_out_attempts_and_points_apis_return_401(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 1005, "bot_owner", "bot@internal.net")
        job = create_job_helper(session, owner.id, "showcase-api-repo", is_showcase=True)
        job_id = job.id

    # 1. Attempts run endpoint
    r_run = client.post(f"/api/attempts/{job_id}/1/run", json={"code": "x = 1"})
    assert r_run.status_code == 401

    # 2. Attempts submit endpoint
    r_sub = client.post(f"/api/attempts/{job_id}/1", json={"submitted_code": "x = 1"})
    assert r_sub.status_code == 401

    # 3. Attempts hint endpoint
    r_hint = client.post(f"/api/attempts/{job_id}/1/hint")
    assert r_hint.status_code == 401

    # 4. Attempts reveal endpoint
    r_rev = client.post(f"/api/attempts/{job_id}/1/reveal")
    assert r_rev.status_code == 401

    # 5. Attempts review endpoint
    r_revw = client.post(f"/api/attempts/{job_id}/1/review")
    assert r_revw.status_code == 401

    # 6. Points ledger/balance endpoint
    r_pts = client.get("/api/points/balance")
    assert r_pts.status_code == 401


# -------------------------------------------------------------------------
# Test: Logged-in non-owner calls attempts and points endpoints for showcase job
# -------------------------------------------------------------------------
def test_logged_in_non_owner_cannot_call_attempts_or_points_for_showcase(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 2001, "showcase_owner_alpha", "alpha@showcase.internal")
        stranger = create_user_helper(session, 2002, "showcase_stranger_beta", "beta@stranger.internal")
        job = create_job_helper(session, owner.id, "showcase-secured-job", is_showcase=True)
        job_id = job.id
        stranger_id = stranger.id
        stranger_github_id = stranger.github_id
        stranger_username = stranger.github_username

    token = create_access_token(
        user_id=stranger_id,
        github_id=stranger_github_id,
        github_username=stranger_username,
    )
    client.cookies.set("access_token", token)

    # 1. Run endpoint
    r_run = client.post(f"/api/attempts/{job_id}/1/run", json={"code": "x = 1"})
    assert r_run.status_code in (401, 403, 404)
    assert r_run.status_code != 200

    # 2. Submit endpoint
    r_sub = client.post(f"/api/attempts/{job_id}/1", json={"submitted_code": "x = 1"})
    assert r_sub.status_code in (401, 403, 404)
    assert r_sub.status_code != 200

    # 3. Hint endpoint
    r_hint = client.post(f"/api/attempts/{job_id}/1/hint")
    assert r_hint.status_code in (401, 403, 404)
    assert r_hint.status_code != 200

    # 4. Reveal endpoint
    r_rev = client.post(f"/api/attempts/{job_id}/1/reveal")
    assert r_rev.status_code in (401, 403, 404)
    assert r_rev.status_code != 200

    # 5. Review endpoint
    r_revw = client.post(f"/api/attempts/{job_id}/1/review")
    assert r_revw.status_code in (401, 403, 404)
    assert r_revw.status_code != 200

    # 6. Points endpoint for job
    r_pts = client.get(f"/api/points/job/{job_id}")
    assert r_pts.status_code in (401, 403, 404)
    assert r_pts.status_code != 200


# -------------------------------------------------------------------------
# Test (e): Owner's name or email is absent from the showcase page
# -------------------------------------------------------------------------
def test_owner_name_and_email_absent_from_showcase_page(test_db, client):
    SessionLocal, _ = test_db
    secret_username = "hyper_unique_showcase_owner_xyz"
    secret_email = "very_confidential_email_xyz@company.org"

    with SessionLocal() as session:
        owner = create_user_helper(session, 1006, secret_username, secret_email)
        job = create_job_helper(session, owner.id, "confidential-showcase-repo", is_showcase=True)
        job_id = job.id
        owner_id = owner.id

    # Logged-out visit
    resp = client.get(f"/report/{job_id}")
    assert resp.status_code == 200
    assert secret_username not in resp.text
    assert secret_email not in resp.text
    assert f"user_id: {owner_id}" not in resp.text and f'"user_id": {owner_id}' not in resp.text and f"user_id={owner_id}" not in resp.text

    # Logged-in as another user visit
    with SessionLocal() as session:
        stranger = create_user_helper(session, 1007, "visitor_one", "visitor@web.com")
        stranger_id = stranger.id
        stranger_github_id = stranger.github_id
        stranger_username = stranger.github_username

    token = create_access_token(
        user_id=stranger_id,
        github_id=stranger_github_id,
        github_username=stranger_username,
    )
    client.cookies.set("access_token", token)

    resp2 = client.get(f"/report/{job_id}")
    assert resp2.status_code == 200
    assert secret_username not in resp2.text
    assert secret_email not in resp2.text


# -------------------------------------------------------------------------
# Test (f): Seed script is idempotent
# -------------------------------------------------------------------------
def test_seed_showcase_is_idempotent(test_db):
    SessionLocal, _ = test_db

    payload = {
        "version": 1,
        "job": {
            "repo_name": "idempotent-seed-repo",
            "github_url": "https://github.com/seed/idempotent-repo",
            "commit_ref": "v1.0",
            "resolved_sha": "seedsha987654321",
            "subpath": None,
            "status": "completed",
            "run_id": "run_idempotent_seed_001",
            "failed_stage": None,
            "error_message": None,
            "execution_time_seconds": 12.5,
            "markdown_output": SAMPLE_REPORT_MD,
            "graph_output_json": "{}",
            "quiz_output_json": "{}",
        },
        "repo": {
            "github_url": "https://github.com/seed/idempotent-repo",
            "commit_hash": "seedsha987654321",
            "status": "complete",
            "error_message": None,
            "expires_at": (utc_now() + timedelta(days=30)).isoformat(),
            "keep_longer": True,
            "consent_prompt_improvement": False,
            "consent_future_training": False,
            "subpath": None,
        },
        "ingestion_result": {
            "file_tree_json": json.dumps([{"path": "index.js", "size_bytes": 100}]),
            "file_contents_json": json.dumps({"index.js": "console.log('hello');"}),
            "skipped_files_json": "[]",
            "redaction_count": 0,
            "clone_duration_ms": 250,
        },
        "analysis_result": {
            "pipeline_result_json": json.dumps({"stages": []}),
            "execution_time_seconds": 12.5,
        },
    }

    with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        with gzip.open(tmp_path, "wt", encoding="utf-8") as f:
            json.dump(payload, f)

        # Patch get_db_session in seed_showcase to use test session
        from contextlib import contextmanager
        @contextmanager
        def mock_get_db():
            s = SessionLocal()
            try:
                yield s
            finally:
                s.close()

        with patch("scripts.seed_showcase.get_db_session", side_effect=mock_get_db), \
             patch("scripts.seed_showcase.init_db"):
            # Run seed 1st time
            job_id_1 = seed_showcase_file(tmp_path)
            assert job_id_1 > 0

            # Run seed 2nd time (must be idempotent)
            job_id_2 = seed_showcase_file(tmp_path)
            assert job_id_2 == job_id_1

            with SessionLocal() as session:
                jobs = session.query(AnalysisJobModel).filter(AnalysisJobModel.run_id == "run_idempotent_seed_001").all()
                assert len(jobs) == 1
                assert jobs[0].is_showcase is True

                repos = session.query(RepoModel).filter(RepoModel.github_url == "https://github.com/seed/idempotent-repo").all()
                assert len(repos) == 1
                assert repos[0].keep_longer is True
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# -------------------------------------------------------------------------
# Test (g): cleanup_expired_records keeps a keep_longer repo
# -------------------------------------------------------------------------
def test_cleanup_expired_records_keeps_keep_longer_repo(test_db):
    SessionLocal, _ = test_db
    past_date = utc_now() - timedelta(days=40)

    with SessionLocal() as session:
        # Repo 1: expired, keep_longer=False -> should be purged
        r_expired = RepoModel(
            github_url="https://github.com/test/purge-me",
            commit_hash="hash_purge",
            status="complete",
            expires_at=past_date,
            keep_longer=False,
        )
        # Repo 2: expired, keep_longer=True -> MUST be preserved
        r_preserved = RepoModel(
            github_url="https://github.com/test/preserve-me",
            commit_hash="hash_keep",
            status="complete",
            expires_at=past_date,
            keep_longer=True,
        )
        session.add_all([r_expired, r_preserved])
        session.commit()

        purged_count = StorageRepository.cleanup_expired_records(session)
        session.commit()

        assert purged_count >= 1

        remaining_purged = session.query(RepoModel).filter(RepoModel.github_url == "https://github.com/test/purge-me").first()
        assert remaining_purged is None

        remaining_preserved = session.query(RepoModel).filter(RepoModel.github_url == "https://github.com/test/preserve-me").first()
        assert remaining_preserved is not None
        assert remaining_preserved.keep_longer is True


# -------------------------------------------------------------------------
# Test (h): /showcase lists only showcase jobs
# -------------------------------------------------------------------------
def test_showcase_directory_lists_only_showcase_jobs(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 1008, "curator_user", "curator@internal.net")
        job_showcase = create_job_helper(session, owner.id, "public-showcase-alpha", is_showcase=True, run_id="run_alpha")
        job_private = create_job_helper(session, owner.id, "strictly-private-beta", is_showcase=False, run_id="run_beta")
        alpha_id = job_showcase.id
        beta_id = job_private.id

    resp = client.get("/showcase")
    assert resp.status_code == 200
    html = resp.text

    assert "public-showcase-alpha" in html
    assert f"/report/{alpha_id}" in html
    assert "strictly-private-beta" not in html
    assert f"/report/{beta_id}" not in html


# -------------------------------------------------------------------------
# Additional Test: /report/{job_id}/milestone/{tier} redirects to /report/{job_id} for showcase
# -------------------------------------------------------------------------
def test_showcase_milestone_tier_redirects_to_report(test_db, client):
    SessionLocal, _ = test_db
    with SessionLocal() as session:
        owner = create_user_helper(session, 1009, "tier_test_user", "tier@internal.net")
        job = create_job_helper(session, owner.id, "tier-redirect-repo", is_showcase=True, run_id="run_tier")
        job_id = job.id

    # Logged out request to milestone route
    resp = client.get(f"/report/{job_id}/milestone/1", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == f"/report/{job_id}"


# -------------------------------------------------------------------------
# Additional Test: export_showcase stops if secrets detected
# -------------------------------------------------------------------------
def test_export_showcase_secret_detection():
    clean_text = "def hello(): return 'world'"
    assert count_secret_matches(clean_text) == 0

    secret_text = "my_api_key = 'sk-1234567890abcdef1234567890abcdef'"
    assert count_secret_matches(secret_text) >= 1

    payload_clean = {"job": {"desc": clean_text}}
    assert len(scan_payload_for_secrets(payload_clean)) == 0

    payload_dirty = {"job": {"desc": secret_text}}
    dirty_matches = scan_payload_for_secrets(payload_dirty)
    assert len(dirty_matches) >= 1
    # Ensure values are not leaked into the keys of dirty_matches
    for k in dirty_matches.keys():
        assert "sk-123" not in k


# -------------------------------------------------------------------------
# Test: Exact match REDACTED skip in export secret scanner
# -------------------------------------------------------------------------
def test_export_showcase_redacted_exact_match():
    assert count_secret_matches('api_key = "[REDACTED]"') == 0
    assert count_secret_matches('api_key = "abcdefgh[REDACTED]"') >= 1

