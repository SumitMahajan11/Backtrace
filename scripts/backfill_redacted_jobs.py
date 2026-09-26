"""Idempotent backfill script to re-ingest and re-persist repository files using the updated SecretScanner.

Usage:
    python scripts/backfill_redacted_jobs.py [--dry-run] [--job-id JOB_ID]
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal
from app.models.db import AnalysisJobModel, IngestionResultModel, RepoModel
from app.services.file_content_service import FileContentService
from app.services.ingestion import IngestionService
from app.security.secret_scanner import SecretScanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_redacted_jobs")


def run_backfill(dry_run: bool = False, job_id: int = None):
    logger.info("Starting secret scanner backfill (dry_run=%s, target_job_id=%s)", dry_run, job_id)
    
    with SessionLocal() as session:
        query = session.query(RepoModel).order_by(RepoModel.id.asc())
        repos = query.all()
        
        total_repos = len(repos)
        scanned_count = 0
        needing_update_count = 0
        updated_count = 0
        skipped_clean_count = 0
        errors_count = 0

        ingestion_service = IngestionService()

        for repo in repos:
            scanned_count += 1
            github_url = repo.github_url
            commit_hash = repo.commit_hash
            ingestion_res = repo.ingestion_result

            if not ingestion_res or not ingestion_res.file_contents_json:
                logger.info("Repo ID=%s (%s): No stored file contents found. Skipping.", repo.id, github_url)
                continue

            try:
                stored_contents = json.loads(ingestion_res.file_contents_json)
            except Exception as e:
                logger.error("Repo ID=%s (%s): Failed to parse file_contents_json: %s", repo.id, github_url, e)
                errors_count += 1
                continue

            # Flag strictly by redaction_count > 0, not '[REDACTED]' substring in source code
            old_redaction_count = ingestion_res.redaction_count or 0
            
            # Check if file_tree_json lacks per-file redaction_count
            tree_lacks_per_file_counts = False
            if ingestion_res.file_tree_json:
                try:
                    tree_data = json.loads(ingestion_res.file_tree_json)
                    if isinstance(tree_data, list):
                        for item in tree_data:
                            if isinstance(item, str) or (isinstance(item, dict) and "redaction_count" not in item):
                                tree_lacks_per_file_counts = True
                                break
                except Exception:
                    tree_lacks_per_file_counts = True

            needs_update = (old_redaction_count > 0) or tree_lacks_per_file_counts

            logger.info(
                "Repo ID=%s (%s): Total files=%d, Recorded redaction_count=%d, lacks_per_file_counts=%s",
                repo.id,
                github_url,
                len(stored_contents),
                old_redaction_count,
                tree_lacks_per_file_counts,
            )

            if not needs_update:
                skipped_clean_count += 1
                logger.info("Repo ID=%s (%s): Stored content is clean with full metadata. No backfill needed.", repo.id, github_url)
                continue

            needing_update_count += 1

            if dry_run:
                logger.info(
                    "[DRY RUN] Repo ID=%s (%s): Would re-fetch at commit %s (subpath=%s) and re-scan %d files.",
                    repo.id,
                    github_url,
                    commit_hash,
                    getattr(repo, "subpath", None),
                    len(stored_contents),
                )
                continue

            # Execute live backfill
            try:
                repo_subpath = getattr(repo, "subpath", None)
                logger.info("Re-ingesting Repo ID=%s (%s) at commit %s (subpath=%s) ...", repo.id, github_url, commit_hash, repo_subpath)
                new_res = ingestion_service.ingest_repository(
                    github_url=github_url,
                    commit_ref=commit_hash if commit_hash not in ("head_latest", "HEAD") else None,
                    subpath=repo_subpath,
                )
                
                # Count actual new redactions from FileNodes
                new_redaction_count = sum(node.redaction_count for node in new_res.file_tree)

                FileContentService.persist_file_contents(
                    session=session,
                    github_url=github_url,
                    file_contents=new_res.file_contents,
                    commit_hash=new_res.metadata.head_commit or commit_hash,
                    subpath=repo_subpath,
                    file_tree=[f.model_dump() if hasattr(f, "model_dump") else f.dict() for f in new_res.file_tree],
                    skipped_items=[s.model_dump() if hasattr(s, "model_dump") else s.dict() for s in new_res.skipped_items],
                    redaction_count=new_redaction_count,
                    clone_duration_ms=int(new_res.metadata.clone_duration_seconds * 1000),
                )
                session.commit()
                updated_count += 1
                logger.info(
                    "Repo ID=%s (%s): Successfully backfilled. New redaction_count=%d (was %d)",
                    repo.id,
                    github_url,
                    new_redaction_count,
                    old_redaction_count,
                )
            except Exception as e:
                logger.error("Repo ID=%s (%s): Re-ingestion failed: %s", repo.id, github_url, e)
                session.rollback()
                errors_count += 1

        print("\n================ BACKFILL SUMMARY ================")
        print(f"Total Repos Checked:   {scanned_count}")
        print(f"Clean Repos Skipped:   {skipped_clean_count}")
        print(f"Repos Needing Update:  {needing_update_count}")
        print(f"Repos Updated:         {updated_count} (dry_run={dry_run})")
        print(f"Errors Encountered:    {errors_count}")
        print("==================================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill stored repo file contents using updated SecretScanner.")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without modifying the database.")
    parser.add_argument("--job-id", type=int, default=None, help="Target specific job ID.")
    args = parser.parse_args()

    run_backfill(dry_run=args.dry_run, job_id=args.job_id)
