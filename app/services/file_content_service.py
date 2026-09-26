"""Service for retrieving, matching, and caching repository source file contents for analysis jobs."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set
from sqlalchemy.orm import Session

from app.models.db import IngestionResultModel, RepoModel, utc_now

logger = logging.getLogger(__name__)

SOURCE_NOT_AVAILABLE_MESSAGE = (
    "# The original source for this file isn't available for this job — "
    "try re-running the analysis to view the real implementation."
)

LEGACY_REFETCH_NOTICE = (
    "# Note: Loaded current version of repository source — content may differ from when analyzed.\n"
)


class FileContentService:
    """Service to access real ingested repository file contents tied to analysis jobs."""

    @classmethod
    def get_file_contents_for_job(
        cls,
        session: Session,
        job: Any,
        allow_refetch: bool = True,
    ) -> Dict[str, str]:
        """
        Retrieves the real ingested file contents for an analysis job.
        
        Resolution order:
        1. Query RepoModel + IngestionResultModel for job (github_url, resolved_sha/commit_ref, subpath) from database.
           Strictly matches subpath: subpath job with no exact row returns empty/SOURCE_NOT_AVAILABLE.
        2. Fallback to node-embedded source_code/content in job.graph_data.
        3. Backward Compatibility (Part D): On-demand re-fetch from original URL if not persisted yet.
           For legacy jobs (resolved_sha is NULL), does NOT stamp job.resolved_sha with HEAD,
           and marks content with "current version, may differ from when analyzed".
        4. Return empty dict if source cannot be retrieved.
        """
        if not job:
            return {}

        github_url = getattr(job, "github_url", None) or getattr(job, "repo_url", None)
        resolved_sha = getattr(job, "resolved_sha", None)
        commit_ref = getattr(job, "commit_ref", None)
        subpath = getattr(job, "subpath", None)
        norm_subpath = subpath.replace("\\", "/").strip("/") if (subpath and subpath.strip()) else None
        target_commit = resolved_sha or commit_ref

        # 1. Check RepoModel + IngestionResultModel in DB keyed strictly by (github_url, resolved_sha/commit_ref, subpath)
        if github_url and session:
            query = session.query(RepoModel).filter(RepoModel.github_url == github_url)
            if target_commit:
                query = query.filter(RepoModel.commit_hash == target_commit)
            if norm_subpath:
                query = query.filter(RepoModel.subpath == norm_subpath)
            else:
                query = query.filter((RepoModel.subpath == None) | (RepoModel.subpath == ""))
            
            repo = query.order_by(RepoModel.id.desc()).first()

            if repo and repo.ingestion_result and repo.ingestion_result.file_contents_json:
                try:
                    contents = json.loads(repo.ingestion_result.file_contents_json)
                    if isinstance(contents, dict) and contents:
                        return contents
                except Exception as e:
                    logger.warning("Failed to deserialize file_contents_json: %s", e)

        # 2. Check graph_data node source_code / content
        graph_data = getattr(job, "graph_data", None)
        if isinstance(graph_data, dict) and "nodes" in graph_data:
            extracted = {}
            for node in graph_data.get("nodes", []):
                p = node.get("path") or node.get("id")
                code = node.get("source_code") or node.get("content")
                if p and code:
                    extracted[p] = code
            if extracted:
                return extracted

        # 3. Backward compatibility on-demand re-fetch (Part D)
        if allow_refetch and github_url and (github_url.startswith("http://") or github_url.startswith("https://")):
            try:
                effective_commit = target_commit
                is_legacy_unversioned = not effective_commit
                if is_legacy_unversioned and session is not None:
                    repo_query = session.query(RepoModel).filter(RepoModel.github_url == github_url)
                    if norm_subpath:
                        repo_query = repo_query.filter(RepoModel.subpath == norm_subpath)
                    else:
                        repo_query = repo_query.filter((RepoModel.subpath == None) | (RepoModel.subpath == ""))
                    repo_rec = repo_query.order_by(RepoModel.id.desc()).first()
                    if repo_rec and repo_rec.commit_hash and repo_rec.commit_hash not in ("head_latest", "HEAD"):
                        effective_commit = repo_rec.commit_hash
                        is_legacy_unversioned = False

                from app.services.ingestion import IngestionService
                ingestion_svc = IngestionService()
                ingest_res = ingestion_svc.ingest_repository(
                    github_url,
                    commit_ref=effective_commit,
                    subpath=norm_subpath,
                )
                if ingest_res and ingest_res.file_contents:
                    head_sha = getattr(ingest_res.metadata, "head_commit", None) or effective_commit or commit_ref
                    
                    # For legacy jobs (resolved_sha is NULL), do NOT stamp job.resolved_sha with current HEAD
                    # Leave job.resolved_sha empty / None

                    # Persist/cache into DB
                    cls.persist_file_contents(
                        session=session,
                        github_url=github_url,
                        file_contents=ingest_res.file_contents,
                        commit_hash=head_sha,
                        subpath=norm_subpath,
                        file_tree=[node.model_dump() for node in ingest_res.file_tree] if ingest_res.file_tree else None,
                        skipped_items=[item.model_dump() for item in ingest_res.skipped_items] if ingest_res.skipped_items else None,
                        clone_duration_ms=int(getattr(ingest_res.metadata, "clone_duration_seconds", 0) * 1000),
                    )

                    # For legacy unversioned re-fetch, mark content with notice
                    if is_legacy_unversioned:
                        annotated_contents = {
                            p: f"{LEGACY_REFETCH_NOTICE}{content}"
                            for p, content in ingest_res.file_contents.items()
                        }
                        return annotated_contents

                    return ingest_res.file_contents
            except Exception as e:
                logger.info("On-demand re-fetch for %s skipped or failed: %s", github_url, e)

        return {}

    @classmethod
    def persist_file_contents(
        cls,
        session: Session,
        github_url: str,
        file_contents: Dict[str, str],
        commit_hash: Optional[str] = None,
        subpath: Optional[str] = None,
        file_tree: Optional[List[Dict[str, Any]]] = None,
        skipped_items: Optional[List[Dict[str, Any]]] = None,
        clone_duration_ms: int = 0,
        redaction_count: int = 0,
    ) -> RepoModel:
        """Persists or updates RepoModel and IngestionResultModel records in database keyed by (github_url, commit_hash, subpath)."""
        head_commit = commit_hash or "head_latest"
        norm_subpath = subpath.replace("\\", "/").strip("/") if (subpath and subpath.strip()) else None

        query = (
            session.query(RepoModel)
            .filter(RepoModel.github_url == github_url)
            .filter(RepoModel.commit_hash == head_commit)
        )
        if norm_subpath:
            query = query.filter(RepoModel.subpath == norm_subpath)
        else:
            query = query.filter((RepoModel.subpath == None) | (RepoModel.subpath == ""))

        repo = query.order_by(RepoModel.id.desc()).first()

        now = utc_now()
        if not repo:
            repo = RepoModel(
                github_url=github_url,
                commit_hash=head_commit,
                subpath=norm_subpath,
                status="complete",
                created_at=now,
                expires_at=now + timedelta(days=30),
            )
            session.add(repo)
            session.flush()
        else:
            repo.status = "complete"
            if norm_subpath:
                repo.subpath = norm_subpath

        file_tree_json = json.dumps(file_tree if file_tree is not None else list(file_contents.keys()))
        file_contents_json = json.dumps(file_contents)
        skipped_files_json = json.dumps(skipped_items if skipped_items is not None else [])

        if repo.ingestion_result:
            repo.ingestion_result.file_tree_json = file_tree_json
            repo.ingestion_result.file_contents_json = file_contents_json
            repo.ingestion_result.skipped_files_json = skipped_files_json
            repo.ingestion_result.redaction_count = redaction_count
            repo.ingestion_result.clone_duration_ms = clone_duration_ms
        else:
            ingestion_payload = IngestionResultModel(
                repo_id=repo.id,
                file_tree_json=file_tree_json,
                file_contents_json=file_contents_json,
                skipped_files_json=skipped_files_json,
                redaction_count=redaction_count,
                clone_duration_ms=clone_duration_ms,
                created_at=now,
            )
            session.add(ingestion_payload)
        session.flush()
        return repo

    @classmethod
    def find_matching_file_content(
        cls,
        file_contents: Dict[str, str],
        target_path: str,
    ) -> Optional[str]:
        """
        Finds the matching file content for target_path from a file_contents mapping
        using robust exact, normalized, suffix, and basename matching.
        """
        if not file_contents or not target_path:
            return None

        # 1. Exact match
        if target_path in file_contents:
            return file_contents[target_path]

        norm_target = target_path.replace("\\", "/").strip("/")

        # 2. Normalized full match
        for k, v in file_contents.items():
            norm_k = k.replace("\\", "/").strip("/")
            if norm_k == norm_target:
                return v

        # 3. Suffix match (e.g. reelclaim-backend/app/db.py matches app/db.py)
        for k, v in file_contents.items():
            norm_k = k.replace("\\", "/").strip("/")
            if norm_k.endswith("/" + norm_target) or norm_target.endswith("/" + norm_k):
                return v

        # 4. Basename match
        target_base = norm_target.split("/")[-1]
        for k, v in file_contents.items():
            norm_k = k.replace("\\", "/").strip("/")
            if norm_k.split("/")[-1] == target_base:
                return v

        return None

    @classmethod
    def get_redacted_files_for_job(
        cls,
        session: Session,
        job: Any,
    ) -> Set[str]:
        """
        Retrieves the exact set of file paths that had secrets redacted by the scanner.
        Uses the per-file redaction_count recorded during ingestion, with backward
        compatibility for legacy rows without per-file redaction counts.
        """
        if not job or not session:
            return set()
        github_url = getattr(job, "github_url", None) or getattr(job, "repo_url", None)
        resolved_sha = getattr(job, "resolved_sha", None)
        commit_ref = getattr(job, "commit_ref", None)
        subpath = getattr(job, "subpath", None)
        norm_subpath = subpath.replace("\\", "/").strip("/") if (subpath and subpath.strip()) else None
        target_commit = resolved_sha or commit_ref

        if github_url:
            query = session.query(RepoModel).filter(RepoModel.github_url == github_url)
            if target_commit:
                query = query.filter(RepoModel.commit_hash == target_commit)
            if norm_subpath:
                query = query.filter(RepoModel.subpath == norm_subpath)
            else:
                query = query.filter((RepoModel.subpath == None) | (RepoModel.subpath == ""))
            repo = query.order_by(RepoModel.id.desc()).first()

            if not repo and target_commit:
                repo = (
                    session.query(RepoModel)
                    .filter(RepoModel.github_url == github_url)
                    .filter(RepoModel.commit_hash == target_commit)
                    .order_by(RepoModel.id.desc())
                    .first()
                )

            if not repo:
                repo = session.query(RepoModel).filter(RepoModel.github_url == github_url).order_by(RepoModel.id.desc()).first()

            if repo and repo.ingestion_result:
                ingest_res = repo.ingestion_result
                redacted = set()
                if ingest_res.file_tree_json:
                    try:
                        tree = json.loads(ingest_res.file_tree_json)
                        has_per_file_counts = False
                        if isinstance(tree, list):
                            for node in tree:
                                if isinstance(node, dict):
                                    if "redaction_count" in node:
                                        has_per_file_counts = True
                                        if node.get("redaction_count", 0) > 0:
                                            p = node.get("path")
                                            if p:
                                                redacted.add(p)
                                                redacted.add(p.replace("\\", "/").strip("/"))
                                elif isinstance(node, str):
                                    pass

                            # If old row lacked per-file redaction_count but overall redaction_count > 0,
                            # re-scan files or inspect contents
                            if not has_per_file_counts and (ingest_res.redaction_count or 0) > 0:
                                if ingest_res.file_contents_json:
                                    contents = json.loads(ingest_res.file_contents_json)
                                    from app.security.secret_scanner import SecretScanner
                                    scanner = SecretScanner()
                                    for p, text in contents.items():
                                        _, file_cnt = scanner.scan_and_redact(text)
                                        if file_cnt > 0 or "[REDACTED]" in text:
                                            redacted.add(p)
                                            redacted.add(p.replace("\\", "/").strip("/"))
                        return redacted
                    except Exception as e:
                        logger.warning("Failed to deserialize file_tree_json for redactions: %s", e)
        return set()

    @classmethod
    def get_milestone_reference_code(
        cls,
        session: Session,
        job: Any,
        milestone_tier: int,
        target_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Retrieves the real source reference implementation for a milestone tier.
        Returns a dict with reference_code, included_files, and has_real_source flag.
        Never falls back silently to fake AST stubs.
        """
        graph_data = getattr(job, "graph_data", None) or {}
        nodes = graph_data.get("nodes", []) if isinstance(graph_data, dict) else []
        tier_nodes = [n for n in nodes if n.get("tier") == milestone_tier]
        included_files = [n.get("path") or n.get("id") for n in tier_nodes if n.get("path") or n.get("id")]

        file_contents = cls.get_file_contents_for_job(session=session, job=job)

        # If target file specified, search for it first
        if target_file:
            content = cls.find_matching_file_content(file_contents, target_file)
            if content:
                return {
                    "milestone_tier": milestone_tier,
                    "target_file": target_file,
                    "included_files": included_files,
                    "reference_code": content,
                    "has_real_source": True,
                }

        # Match all files for this milestone tier
        matched_pieces = []
        for f_path in included_files:
            c = cls.find_matching_file_content(file_contents, f_path)
            if not c and "nodes" in graph_data:
                for n in graph_data.get("nodes", []):
                    n_p = n.get("path") or n.get("id") or ""
                    if n_p == f_path or n_p.endswith(f_path) or f_path.endswith(n_p):
                        if n.get("source_code") or n.get("content"):
                            c = n.get("source_code") or n.get("content")
                            break
            if c:
                matched_pieces.append((f_path, c))

        if matched_pieces:
            if len(matched_pieces) == 1:
                ref_code = matched_pieces[0][1]
            else:
                ref_code = "\n\n".join(
                    f"# ====================================================================\n"
                    f"# File: {path}\n"
                    f"# ====================================================================\n"
                    f"{content}"
                    for path, content in matched_pieces
                )
            return {
                "milestone_tier": milestone_tier,
                "included_files": included_files,
                "reference_code": ref_code,
                "has_real_source": True,
            }

        # When real source is genuinely not available, return SOURCE_NOT_AVAILABLE_MESSAGE
        return {
            "milestone_tier": milestone_tier,
            "included_files": included_files,
            "reference_code": SOURCE_NOT_AVAILABLE_MESSAGE,
            "has_real_source": False,
        }
