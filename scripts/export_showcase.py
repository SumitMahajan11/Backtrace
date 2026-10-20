#!/usr/bin/env python3
"""Showcase Job Exporter.

Exports an AnalysisJobModel, its RepoModel, IngestionResultModel, and AnalysisResultModel
to a compressed JSON file (.json.gz).
Does NOT export users, milestone_attempts, or points_ledger.
Scans all exported contents for secrets/keys/tokens/passwords prior to writing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from typing import Any, Dict, Optional

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import get_db_session, init_db
from app.models.db import (
    AnalysisJobModel,
    AnalysisResultModel,
    IngestionResultModel,
    RepoModel,
)


SECRET_PATTERNS = [
    re.compile(r"(?i)(?:api_key|apikey|secret_key|auth_token|access_token|private_key|client_secret|password)\s*[:=]\s*['\"]([^'\"]{8,})['\"]"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"),
    re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:postgres|mysql|mongodb|redis):\/\/[a-zA-Z0-9_]+:[^@\s]+@[a-zA-Z0-9_.-]+"),
]


def count_secret_matches(text: str) -> int:
    """Counts occurrences matching secret/token/password regexes without capturing values."""
    if not text or not isinstance(text, str):
        return 0
    total = 0
    for pat in SECRET_PATTERNS:
        matches = pat.findall(text)
        for m in matches:
            if isinstance(m, str) and "[REDACTED]" in m:
                continue
            total += 1
    return total


def scan_payload_for_secrets(data: Any, path_prefix: str = "") -> Dict[str, int]:
    """Recursively scans exported data for secret patterns and returns match counts per path."""
    matches: Dict[str, int] = {}
    if isinstance(data, dict):
        if "file_contents_json" in data and isinstance(data["file_contents_json"], str):
            try:
                fc_map = json.loads(data["file_contents_json"])
                if isinstance(fc_map, dict):
                    for fpath, fcontent in fc_map.items():
                        c = count_secret_matches(str(fcontent))
                        if c > 0:
                            matches[fpath] = c
            except Exception:
                pass
        for k, v in data.items():
            if k == "file_contents_json":
                continue
            sub = scan_payload_for_secrets(v, f"{path_prefix}.{k}" if path_prefix else k)
            for sp, cnt in sub.items():
                matches[sp] = matches.get(sp, 0) + cnt
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            sub = scan_payload_for_secrets(item, f"{path_prefix}[{idx}]")
            for sp, cnt in sub.items():
                matches[sp] = matches.get(sp, 0) + cnt
    elif isinstance(data, str):
        c = count_secret_matches(data)
        if c > 0:
            matches[path_prefix or "text"] = c
    return matches


def export_showcase_job(job_id: int, out_path: str) -> None:
    """Exports a job and related models to .json.gz with secret verification."""
    init_db()
    with get_db_session() as session:
        job = session.query(AnalysisJobModel).filter(AnalysisJobModel.id == job_id).first()
        if not job:
            print(f"Error: Analysis job ID {job_id} not found in database.", file=sys.stderr)
            sys.exit(1)

        # Lookup corresponding repo
        query = session.query(RepoModel).filter(RepoModel.github_url == job.github_url)
        if job.resolved_sha or job.commit_ref:
            target_commit = job.resolved_sha or job.commit_ref
            query = query.filter(RepoModel.commit_hash == target_commit)
        if job.subpath:
            query = query.filter(RepoModel.subpath == job.subpath)
        repo = query.order_by(RepoModel.created_at.desc()).first()

        ing = repo.ingestion_result if repo else None
        ar = repo.analysis_result if repo else None

        # Build payload explicitly excluding users, attempts, points
        payload = {
            "version": 1,
            "job": {
                "repo_name": job.repo_name,
                "github_url": job.github_url,
                "commit_ref": job.commit_ref,
                "resolved_sha": job.resolved_sha,
                "subpath": job.subpath,
                "status": job.status,
                "run_id": job.run_id,
                "failed_stage": job.failed_stage,
                "error_message": job.error_message,
                "execution_time_seconds": job.execution_time_seconds,
                "markdown_output": job.markdown_output,
                "graph_output_json": job.graph_output_json,
                "quiz_output_json": job.quiz_output_json,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            },
            "repo": {
                "github_url": repo.github_url,
                "commit_hash": repo.commit_hash,
                "status": repo.status,
                "error_message": repo.error_message,
                "created_at": repo.created_at.isoformat() if repo.created_at else None,
                "expires_at": repo.expires_at.isoformat() if repo.expires_at else None,
                "keep_longer": True,
                "consent_prompt_improvement": repo.consent_prompt_improvement,
                "consent_future_training": repo.consent_future_training,
                "subpath": repo.subpath,
            } if repo else None,
            "ingestion_result": {
                "file_tree_json": ing.file_tree_json,
                "file_contents_json": ing.file_contents_json,
                "skipped_files_json": ing.skipped_files_json,
                "redaction_count": ing.redaction_count,
                "clone_duration_ms": ing.clone_duration_ms,
                "created_at": ing.created_at.isoformat() if ing.created_at else None,
            } if ing else None,
            "analysis_result": {
                "pipeline_result_json": ar.pipeline_result_json,
                "execution_time_seconds": ar.execution_time_seconds,
                "created_at": ar.created_at.isoformat() if ar.created_at else None,
            } if ar else None,
        }

    # Step 5b: Scan before writing
    secret_matches = scan_payload_for_secrets(payload)
    total_matches = sum(secret_matches.values())
    print(f"Secret-scan match count: {total_matches}")
    if secret_matches:
        for fpath, cnt in sorted(secret_matches.items()):
            print(f"Secret pattern match count in {fpath}: {cnt}")
        print("Export failed: Secrets/tokens/passwords detected in export payload. Aborting.")
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Successfully exported showcase job {job_id} to {out_path} (0 secret patterns detected).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export showcase analysis job to compressed JSON.")
    parser.add_argument("--job-id", type=int, required=True, help="Job ID to export")
    parser.add_argument("--out", type=str, required=True, help="Output .json.gz file path")
    args = parser.parse_args()

    export_showcase_job(job_id=args.job_id, out_path=args.out)


if __name__ == "__main__":
    main()
