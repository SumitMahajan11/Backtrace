#!/usr/bin/env python3
"""Showcase Job Seeder.

Reads a compressed JSON payload (.json.gz) exported by export_showcase.py.
Idempotently creates or reuses a stub showcase user, sets is_showcase=True on the job,
and sets keep_longer=True on the repository.
Reads target DB from environment and NEVER prints DB URL, keys, tokens, or credentials.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
from datetime import datetime, timedelta

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import get_db_session, init_db
from app.models.db import (
    AnalysisJobModel,
    AnalysisResultModel,
    IngestionResultModel,
    RepoModel,
    UserModel,
    utc_now,
)


def seed_showcase_file(in_path: str) -> int:
    """Seeds showcase records into the target database idempotently. Returns job ID."""
    if not os.path.exists(in_path):
        print(f"Error: Input file {in_path} does not exist.", file=sys.stderr)
        sys.exit(1)

    with gzip.open(in_path, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    job_data = payload.get("job")
    if not job_data:
        print("Error: Invalid showcase package: missing 'job' data.", file=sys.stderr)
        sys.exit(1)

    repo_data = payload.get("repo")
    ing_data = payload.get("ingestion_result")
    ar_data = payload.get("analysis_result")

    init_db()
    with get_db_session() as session:
        # 1. Idempotently create or reuse stub showcase user
        showcase_user = (
            session.query(UserModel)
            .filter(UserModel.github_username == "showcase_bot")
            .first()
        )
        if not showcase_user:
            showcase_user = UserModel(
                github_id=99999999,
                github_username="showcase_bot",
                email="showcase@backtrace.internal",
                is_admin=False,
            )
            session.add(showcase_user)
            session.flush()

        # 2. Idempotently create or update RepoModel with keep_longer=True
        repo = None
        if repo_data:
            gh_url = repo_data.get("github_url")
            commit_hash = repo_data.get("commit_hash")
            subpath = repo_data.get("subpath")

            query = session.query(RepoModel).filter(
                RepoModel.github_url == gh_url,
                RepoModel.commit_hash == commit_hash,
            )
            if subpath:
                query = query.filter(RepoModel.subpath == subpath)
            repo = query.first()

            if not repo:
                expires_dt = None
                if repo_data.get("expires_at"):
                    try:
                        expires_dt = datetime.fromisoformat(repo_data["expires_at"])
                    except Exception:
                        expires_dt = None
                if not expires_dt:
                    expires_dt = utc_now() + timedelta(days=365)

                repo = RepoModel(
                    github_url=gh_url,
                    commit_hash=commit_hash,
                    status=repo_data.get("status", "complete"),
                    error_message=repo_data.get("error_message"),
                    created_at=utc_now(),
                    expires_at=expires_dt,
                    keep_longer=True,
                    consent_prompt_improvement=repo_data.get("consent_prompt_improvement", False),
                    consent_future_training=repo_data.get("consent_future_training", False),
                    subpath=subpath,
                )
                session.add(repo)
                session.flush()
            else:
                repo.keep_longer = True
                session.flush()

            # 3. Seed IngestionResultModel attached to repo
            if ing_data:
                if not repo.ingestion_result:
                    ing = IngestionResultModel(
                        repo_id=repo.id,
                        file_tree_json=ing_data.get("file_tree_json", "{}"),
                        file_contents_json=ing_data.get("file_contents_json", "{}"),
                        skipped_files_json=ing_data.get("skipped_files_json", "[]"),
                        redaction_count=ing_data.get("redaction_count", 0),
                        clone_duration_ms=ing_data.get("clone_duration_ms", 0),
                    )
                    session.add(ing)
                else:
                    repo.ingestion_result.file_tree_json = ing_data.get("file_tree_json", "{}")
                    repo.ingestion_result.file_contents_json = ing_data.get("file_contents_json", "{}")
                    repo.ingestion_result.skipped_files_json = ing_data.get("skipped_files_json", "[]")
                    repo.ingestion_result.redaction_count = ing_data.get("redaction_count", 0)

            # 4. Seed AnalysisResultModel attached to repo
            if ar_data:
                if not repo.analysis_result:
                    ar = AnalysisResultModel(
                        repo_id=repo.id,
                        pipeline_result_json=ar_data.get("pipeline_result_json", "{}"),
                        execution_time_seconds=ar_data.get("execution_time_seconds", 0.0),
                    )
                    session.add(ar)
                else:
                    repo.analysis_result.pipeline_result_json = ar_data.get("pipeline_result_json", "{}")
                    repo.analysis_result.execution_time_seconds = ar_data.get("execution_time_seconds", 0.0)

            session.flush()

        # 5. Idempotently create or update AnalysisJobModel with is_showcase=True
        run_id = job_data.get("run_id")
        job = None
        if run_id:
            job = session.query(AnalysisJobModel).filter(AnalysisJobModel.run_id == run_id).first()

        if not job:
            job = AnalysisJobModel(
                user_id=showcase_user.id,
                repo_name=job_data.get("repo_name", "Repository"),
                github_url=job_data.get("github_url", ""),
                commit_ref=job_data.get("commit_ref"),
                resolved_sha=job_data.get("resolved_sha"),
                subpath=job_data.get("subpath"),
                status=job_data.get("status", "complete"),
                run_id=run_id or f"showcase_{int(utc_now().timestamp())}",
                failed_stage=job_data.get("failed_stage"),
                error_message=job_data.get("error_message"),
                execution_time_seconds=job_data.get("execution_time_seconds", 0.0),
                markdown_output=job_data.get("markdown_output", ""),
                graph_output_json=job_data.get("graph_output_json", "{}"),
                quiz_output_json=job_data.get("quiz_output_json", "{}"),
                is_showcase=True,
            )
            session.add(job)
        else:
            job.user_id = showcase_user.id
            job.repo_name = job_data.get("repo_name", job.repo_name)
            job.github_url = job_data.get("github_url", job.github_url)
            job.commit_ref = job_data.get("commit_ref", job.commit_ref)
            job.resolved_sha = job_data.get("resolved_sha", job.resolved_sha)
            job.subpath = job_data.get("subpath", job.subpath)
            job.status = job_data.get("status", job.status)
            job.failed_stage = job_data.get("failed_stage", job.failed_stage)
            job.error_message = job_data.get("error_message", job.error_message)
            job.execution_time_seconds = job_data.get("execution_time_seconds", job.execution_time_seconds)
            job.markdown_output = job_data.get("markdown_output", job.markdown_output)
            job.graph_output_json = job_data.get("graph_output_json", job.graph_output_json)
            job.quiz_output_json = job_data.get("quiz_output_json", job.quiz_output_json)
            job.is_showcase = True

        session.commit()
        seeded_id = job.id

    print(f"Successfully seeded showcase job (ID: {seeded_id}, is_showcase=True, keep_longer=True).")
    return seeded_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed showcase analysis job into target database.")
    parser.add_argument("--in", dest="in_path", type=str, required=True, help="Input .json.gz file path")
    args = parser.parse_args()

    seed_showcase_file(in_path=args.in_path)


if __name__ == "__main__":
    main()
