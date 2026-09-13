"""Layer 3 Historical Signal Extraction Service.

Uses subprocess git log (not GitPython diff walk) for production-grade performance.
GitPython's per-commit diff() walk is O(commits × files_per_commit) through Python — benchmarks
show 4+ minutes for a 5,557-commit repo. subprocess git log --name-status completes the same
walk in ~2 seconds by delegating diff computation to native C git.

Bug A fix (restructure-date collision): After the main log walk, any file whose first-appearance
timestamp is shared with >= BATCH_RESTRUCTURE_THRESHOLD other files is assumed to have been part
of a batch restructure commit. For those files, a targeted `git log --follow` call retrieves the
true cross-directory creation date, tracking across directory renames. This prevents
artificially-collided timestamps from feeding into Stage B's all-distinct guard and suppressing
History tie-breaking.

Rename attribution: `git log --follow` is also used for any file where the introduction event
was itself a rename (R status in git log --name-status), recovering the original creation date.
"""

import subprocess
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

from app.models.history import (
    CommitHistoryResult,
    CommitSummary,
    FileChange,
    FirstAppearance,
)

# Files whose first-appearance timestamp is shared with at least this many others
# are candidates for a restructure-date second-pass using git log --follow.
# Threshold of 2 means any co-committed pair triggers the check — this catches
# small feature+test batch commits AND large directory restructures.
BATCH_RESTRUCTURE_THRESHOLD = 2


class HistoryExtractorService:
    """Extracts historical commit logs, rename chains, and build-order signals."""

    def extract_history(
        self, repo_dir: Path, max_commits: Optional[int] = None
    ) -> CommitHistoryResult:
        """
        Extracts commit history for a cloned Git repository directory.
        Short-circuits safely if no .git directory exists (zip upload case).

        Uses subprocess git log for production reliability (completes in seconds,
        not minutes). GitPython diff walk is NOT used because it requires ~4+ minutes
        for repos with 5,000+ commits, making it incompatible with any web request
        timeout.

        If max_commits is None, processes all commits (full walk) so that
        file_first_appearance timestamps are accurate. If a cap is supplied,
        commit_count_total vs commit_count_processed will differ, and
        history_confidence is set to 'reduced' to surface this in downstream layers.
        """
        git_dir = repo_dir / ".git"
        if not git_dir.exists():
            return CommitHistoryResult(
                history_available=False,
                history_confidence="reduced",
                commit_count_processed=0,
                commit_count_total=0,
            )

        # Step 0: Get true total commit count (needed for cap reporting)
        total_commit_count = self._get_total_commit_count(repo_dir)

        # Step 1: Full repo-wide log walk via git log --name-status (native C git)
        try:
            result = self._run_git_log(repo_dir, max_commits, total_commit_count)
        except Exception as exc:
            return CommitHistoryResult(
                history_available=False,
                history_confidence="reduced",
                commit_count_processed=0,
                commit_count_total=0,
            )

        if not result.history_available:
            return result

        # Step 2: Detect and fix batch-restructure timestamp collisions (Bug A fix).
        # Files sharing a timestamp with >= BATCH_RESTRUCTURE_THRESHOLD others are
        # candidates for a per-file git log --follow to retrieve their true
        # pre-restructure creation date.
        result = self._fix_restructure_timestamps(repo_dir, result)

        return result

    # ------------------------------------------------------------------
    # Internal: subprocess git log walk
    # ------------------------------------------------------------------

    def _get_total_commit_count(self, repo_dir: Path) -> int:
        """Returns total commit count via git rev-list --count HEAD. Returns 0 on failure."""
        try:
            proc = subprocess.run(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
                timeout=30,
            )
            return int(proc.stdout.strip())
        except Exception:
            return 0

    def _is_shallow_repository(self, repo_dir: Path) -> bool:
        """Returns True if the repository is a shallow clone (e.g. cloned with --depth)."""
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
                timeout=10,
            )
            return proc.stdout.strip().lower() == "true"
        except Exception:
            return False

    def _run_git_log(
        self, repo_dir: Path, max_commits: Optional[int], total_commit_count: int = 0
    ) -> CommitHistoryResult:
        """Runs git log --name-status and parses output into CommitHistoryResult."""
        cmd = [
            "git",
            "log",
            "--name-status",
            "-M",  # detect renames; R-status lines have old_path\tnew_path
            "--format=COMMIT:%H|%cI|%an|%s",
        ]
        if max_commits is not None and max_commits > 0:
            cmd = ["git", "log", f"-n{max_commits}", "--name-status", "-M", "--format=COMMIT:%H|%cI|%an|%s"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
                timeout=120,  # Hard timeout: git log should never take >2 minutes.
            )
        except subprocess.TimeoutExpired:
            return CommitHistoryResult(
                history_available=False,
                history_confidence="reduced",
                commit_count_processed=0,
                commit_count_total=0,
            )
        except subprocess.CalledProcessError:
            return CommitHistoryResult(
                history_available=False,
                history_confidence="reduced",
                commit_count_processed=0,
                commit_count_total=0,
            )

        lines = proc.stdout.splitlines()

        first_appearance_map: Dict[str, FirstAppearance] = {}
        commit_summaries: List[CommitSummary] = []
        current_commit_hash = ""
        current_timestamp = ""
        current_author = ""
        current_msg = ""
        current_changes: List[FileChange] = []
        total_commits = 0
        paths_seen: set = set()

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("COMMIT:"):
                # Flush previous commit
                if current_commit_hash:
                    commit_summaries.append(
                        CommitSummary(
                            hash=current_commit_hash,
                            author=current_author,
                            timestamp=current_timestamp,
                            message=current_msg,
                            files_changed=current_changes,
                        )
                    )
                    current_changes = []

                parts = line[7:].split("|", 3)
                current_commit_hash = parts[0]
                current_timestamp = parts[1] if len(parts) > 1 else ""
                current_author = parts[2] if len(parts) > 2 else ""
                current_msg = parts[3] if len(parts) > 3 else ""
                total_commits += 1
                continue

            parts = line.split("\t")
            if len(parts) < 2:
                continue

            status = parts[0]

            if status.startswith("R") and len(parts) >= 3:
                # Rename: parts[1] = old path, parts[2] = new path
                # git log -M walks newest→oldest: at this commit, old_path became new_path.
                # new_path is introduced here; old_path's creation is its original introduction.
                # We record new_path with this (rename) commit for now;
                # the final first_appearance_map value for old_path (set by later/older commits)
                # will reflect the true creation date.
                old_path = parts[1].replace("\\", "/")
                new_path = parts[2].replace("\\", "/")
                paths_seen.add(new_path)
                paths_seen.add(old_path)
                # Tentatively: new_path was introduced at this commit (rename commit)
                first_appearance_map[new_path] = FirstAppearance(
                    commit_hash=current_commit_hash,
                    timestamp=current_timestamp,
                    was_rename=True,
                    original_path=old_path,
                )
                current_changes.append(FileChange(path=new_path, change_type="renamed", old_path=old_path))
                continue

            path = parts[1].replace("\\", "/")
            paths_seen.add(path)

            # Overwrite on each occurrence: git log walks newest→oldest,
            # so later overwrites are from earlier (older) commits.
            # The final value for each path is its creation commit.
            first_appearance_map[path] = FirstAppearance(
                commit_hash=current_commit_hash,
                timestamp=current_timestamp,
                was_rename=False,
            )

            change_type = (
                "added"
                if status.startswith("A")
                else ("deleted" if status.startswith("D") else "modified")
            )
            current_changes.append(FileChange(path=path, change_type=change_type))

        # Flush final commit
        if current_commit_hash:
            commit_summaries.append(
                CommitSummary(
                    hash=current_commit_hash,
                    author=current_author,
                    timestamp=current_timestamp,
                    message=current_msg,
                    files_changed=current_changes,
                )
            )

        processed_count = len(commit_summaries)
        # Use the pre-queried total; fall back to parsed total if query failed
        effective_total = total_commit_count if total_commit_count > 0 else total_commits

        # Rename propagation: for files recorded as renames, propagate the original
        # path's creation date back to the renamed file.
        # git log -M walking newest→oldest sets new_path→rename_commit first.
        # After the full walk, old_path has its true creation commit recorded.
        # Update new_path to point to old_path's creation commit unconditionally:
        # by definition, old_path existed before new_path (which is the renamed form).
        for new_path, fa in list(first_appearance_map.items()):
            if fa.was_rename and fa.original_path:
                orig_fa = first_appearance_map.get(fa.original_path)
                if orig_fa and orig_fa.commit_hash:
                    first_appearance_map[new_path] = FirstAppearance(
                        commit_hash=orig_fa.commit_hash,
                        timestamp=orig_fa.timestamp,
                        was_rename=True,
                        original_path=fa.original_path,
                    )

        is_shallow = self._is_shallow_repository(repo_dir)

        # Detect squashed/rebased/partial/shallow history
        confidence = self._evaluate_confidence(
            total_commit_count=effective_total,
            unique_paths=len(paths_seen),
            processed_count=processed_count,
            max_commits=max_commits,
            is_shallow=is_shallow,
        )

        return CommitHistoryResult(
            history_available=True,
            commits=commit_summaries,
            file_first_appearance=first_appearance_map,
            history_confidence=confidence,
            commit_count_processed=processed_count,
            commit_count_total=effective_total,
        )

    # ------------------------------------------------------------------
    # Internal: Bug A fix — restructure-date collision correction
    # ------------------------------------------------------------------

    def _fix_restructure_timestamps(
        self, repo_dir: Path, result: CommitHistoryResult
    ) -> CommitHistoryResult:
        """
        Detects files with batch-restructure timestamps and runs git log --follow
        to recover their true pre-restructure creation dates.

        A batch restructure commit is identified when >= BATCH_RESTRUCTURE_THRESHOLD
        files share the exact same first-appearance timestamp — a pattern that almost
        never occurs in normal development but is characteristic of 'move everything
        to src/' style directory restructures.

        For each such file, git log --follow is run individually to find the
        oldest commit that touched the file under any path name. This is O(N) in
        the number of restructure-affected files, which in practice is small (tens of
        files, not thousands).
        """
        if not result.file_first_appearance:
            return result

        # Count how many files share each timestamp
        ts_counts = Counter(
            fa.timestamp for fa in result.file_first_appearance.values() if fa.timestamp
        )

        # Timestamps shared by >= BATCH_RESTRUCTURE_THRESHOLD files
        restructure_timestamps = {
            ts for ts, count in ts_counts.items()
            if count >= BATCH_RESTRUCTURE_THRESHOLD
        }

        if not restructure_timestamps:
            return result

        # For each affected file, run git log --follow to find true creation date
        updated_map = dict(result.file_first_appearance)
        fixes_applied = 0

        for path, fa in result.file_first_appearance.items():
            if fa.timestamp not in restructure_timestamps:
                continue

            # Only run targeted --follow for files currently present in the repository
            if not (repo_dir / path).exists():
                continue

            true_ts, true_hash = self._get_true_creation_date(repo_dir, path)
            if true_ts and true_ts != fa.timestamp:
                updated_map[path] = FirstAppearance(
                    commit_hash=true_hash or fa.commit_hash,
                    timestamp=true_ts,
                    was_rename=True,  # True creation was under a different path
                    original_path=path,
                )
                fixes_applied += 1

        return CommitHistoryResult(
            history_available=result.history_available,
            commits=result.commits,
            file_first_appearance=updated_map,
            history_confidence=result.history_confidence,
            commit_count_processed=result.commit_count_processed,
            commit_count_total=result.commit_count_total,
        )

    def _get_true_creation_date(
        self, repo_dir: Path, path: str
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Runs git log --follow to find the oldest commit touching this file under any path.
        Returns (timestamp_iso, commit_hash) or (None, None) on failure.
        """
        try:
            proc = subprocess.run(
                ["git", "log", "--follow", "--format=%H|%cI", "--", path],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                check=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            return None, None

        lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
        if not lines:
            return None, None

        # git log walks newest→oldest; last line is the oldest (true creation) commit
        oldest = lines[-1]
        parts = oldest.split("|", 1)
        if len(parts) < 2:
            return None, None
        return parts[1], parts[0]

    # ------------------------------------------------------------------
    # Internal: Confidence evaluation
    # ------------------------------------------------------------------

    def _evaluate_confidence(
        self,
        total_commit_count: int,
        unique_paths: int,
        processed_count: int,
        max_commits: Optional[int],
        is_shallow: bool = False,
    ) -> str:
        """
        Returns 'high' or 'reduced' confidence based on history characteristics.

        'reduced' is set when:
        - The repository is a shallow clone (commits truncated by --depth).
        - A processing cap or truncation occurred (processed_count < total_commit_count),
          meaning file_first_appearance may be incomplete for files introduced
          only in older commits.
        - Commit count is suspiciously small relative to total unique paths,
          suggesting a squashed or rebased history.
        """
        if is_shallow:
            return "reduced"

        if total_commit_count > 0 and processed_count < total_commit_count:
            return "reduced"

        if total_commit_count < 3 and unique_paths > 10:
            return "reduced"
        if total_commit_count == 1 and unique_paths > 3:
            return "reduced"

        return "high"
