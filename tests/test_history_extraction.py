"""Unit and integration tests for Layer 3 Historical Signal Extraction."""

import os
import subprocess
from pathlib import Path
import pytest

from app.services.history_extractor import HistoryExtractorService


def test_rename_attribution(tmp_path):
    """
    Acceptance Criteria 2: A file renamed partway through history is correctly
    attributed to its original introduction commit, not treated as newly created at rename.
    """
    repo_dir = tmp_path / "rename_repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Commit 1: Add original file
    (repo_dir / "old_name.txt").write_text("Hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True)

    res1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True)
    commit1_hash = res1.stdout.strip()

    # Commit 2: Rename file
    subprocess.run(["git", "mv", "old_name.txt", "new_name.txt"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Rename file"], cwd=repo_dir, check=True)

    service = HistoryExtractorService()
    result = service.extract_history(repo_dir)

    assert result.history_available is True
    assert len(result.commits) == 2

    # Verify first appearance of new_name.txt is linked to commit1_hash
    assert "new_name.txt" in result.file_first_appearance
    fa = result.file_first_appearance["new_name.txt"]
    assert fa.commit_hash == commit1_hash
    assert fa.was_rename is True


def test_squash_history_detection(tmp_path):
    """
    Acceptance Criteria 3: A repo with artificially squashed history
    is flagged with reduced confidence.
    """
    repo_dir = tmp_path / "squashed_repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Single commit containing 12 files
    for i in range(12):
        (repo_dir / f"file_{i}.py").write_text(f"print({i})", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Squashed initial commit"], cwd=repo_dir, check=True)

    service = HistoryExtractorService()
    result = service.extract_history(repo_dir)

    assert result.history_available is True
    assert result.history_confidence == "reduced"


def test_zip_upload_no_git_fallback(tmp_path):
    """
    Acceptance Criteria 4: A repo processed via zip upload path (no .git)
    returns a clean history_available: False result without erroring.
    """
    no_git_dir = tmp_path / "zip_extracted"
    no_git_dir.mkdir()
    (no_git_dir / "index.py").write_text("print('hello')", encoding="utf-8")

    service = HistoryExtractorService()
    result = service.extract_history(no_git_dir)

    assert result.history_available is False
    assert result.history_confidence == "reduced"
    assert result.commit_count_processed == 0
    assert result.commit_count_total == 0


def test_commit_processing_cap(tmp_path):
    """
    Acceptance Criteria 5: A repo with commit history respects the processing cap
    and clearly reports total vs processed count.
    """
    repo_dir = tmp_path / "capped_repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # 10 commits
    for i in range(10):
        (repo_dir / f"file_{i}.txt").write_text(f"version {i}", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", f"Commit {i}"], cwd=repo_dir, check=True)

    service = HistoryExtractorService()
    result = service.extract_history(repo_dir, max_commits=4)

    assert result.history_available is True
    assert result.commit_count_processed == 4
    assert result.commit_count_total == 10
    assert len(result.commits) == 4


def test_real_workspace_history_extraction():
    """
    Test extraction against actual project repository history.
    """
    workspace_dir = Path.cwd()
    if (workspace_dir / ".git").exists():
        service = HistoryExtractorService()
        result = service.extract_history(workspace_dir)

        assert result.history_available is True
        assert result.commit_count_total >= 1
        assert len(result.commits) > 0


def test_partial_walk_reduces_confidence_and_propagates_downstream(tmp_path):
    """
    Safety Test:
    When a walk is incomplete/partial (processed_count < total_commit_count),
    1. history_confidence must be 'reduced'.
    2. Stage B tie breaker must refuse to use history and fall back to heuristic/unresolved.
    3. Stage C scorer must label files 'low' with 'reduced history confidence' reason string.
    """
    from app.sequence.baseline_ordering import BaselineOrderingEngine
    from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
    from app.sequence.confidence_scoring import ConfidenceScoringEngine
    from app.sequence.schema import BaselineOrderingResult, NodeMetadata, Tier

    repo_dir = tmp_path / "partial_walk_repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Create 10 distinct commits for 10 files
    for i in range(10):
        (repo_dir / f"file_{i}.py").write_text(f"def fn_{i}(): pass", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", f"Add file {i}"], cwd=repo_dir, check=True)

    # Step 1: Run extractor with a partial walk cap (processed 3 of 10)
    service = HistoryExtractorService()
    history_res = service.extract_history(repo_dir, max_commits=3)

    assert history_res.history_available is True
    assert history_res.commit_count_processed == 3
    assert history_res.commit_count_total == 10
    # ASSERTION 1: history_confidence is 'reduced'
    assert history_res.history_confidence == "reduced"

    # Step 2: Pass to Stage B
    baseline = BaselineOrderingResult(
        tiers=[Tier(tier_index=0, files=["file_0.py", "file_1.py"])],
        node_metadata={
            "file_0.py": NodeMetadata(path="file_0.py", domain="backend"),
            "file_1.py": NodeMetadata(path="file_1.py", domain="backend"),
        },
    )
    tie_breaker = ConstrainedTieBreakerEngine()
    refined = tie_breaker.refine_baseline_order(baseline, commit_history=history_res)

    # ASSERTION 2: Stage B refused history tie-breaking (fell back to unresolved since same domain)
    for entry in refined.tiers[0].ordered_files:
        assert entry.tie_break_method != "history"
        assert entry.tie_break_method == "unresolved"

    # Step 3: Pass to Stage C
    scorer = ConfidenceScoringEngine()
    scored = scorer.compute_confidence_scores(refined, commit_history=history_res)

    # ASSERTION 3: Stage C labels files 'low' with reduced history confidence reason
    assert len(scored.files) == 2
    for f in scored.files:
        assert f.confidence == "low"
        assert f.confidence_reason == "reduced history confidence (squashed or rebased commits)"


def test_shallow_clone_detection_reduces_confidence(tmp_path):
    """
    Safety Test:
    When a repository is a shallow clone (git clone --depth 1),
    _is_shallow_repository detects it and flags history_confidence as 'reduced'.
    """
    origin_dir = tmp_path / "origin_repo"
    origin_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=origin_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=origin_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=origin_dir, check=True)

    # 5 commits in origin
    for i in range(5):
        (origin_dir / f"file_{i}.txt").write_text(f"data {i}", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=origin_dir, check=True)
        subprocess.run(["git", "commit", "-m", f"commit {i}"], cwd=origin_dir, check=True)

    # Shallow clone with depth 1
    shallow_dir = tmp_path / "shallow_clone"
    subprocess.run(
        ["git", "clone", "--depth", "1", f"file://{origin_dir.resolve().as_posix()}", str(shallow_dir)],
        check=True,
        capture_output=True,
    )

    service = HistoryExtractorService()
    history_res = service.extract_history(shallow_dir)

    assert history_res.history_available is True
    # In shallow clone, rev-list and log both see only 1 commit, but is_shallow flag catches it:
    assert history_res.history_confidence == "reduced"


def test_restructure_directory_move_true_creation_recovery(tmp_path):
    """
    Bug A Regression Test:
    When a directory is moved (e.g. flask/ -> src/flask/) in a batch restructure commit,
    extract_history must recover the true pre-restructure creation date and commit hash
    for each moved file, rather than attributing them to the restructure commit date.
    """
    repo_dir = tmp_path / "restructure_repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    # Commit 1 (2020): Add flask/app.py and flask/config.py
    flask_dir = repo_dir / "flask"
    flask_dir.mkdir()
    (flask_dir / "app.py").write_text("class Flask: pass", encoding="utf-8")
    (flask_dir / "config.py").write_text("class Config: pass", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial flask core"], cwd=repo_dir, check=True)
    c1_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True).stdout.strip()

    # Commit 2 (2021): Add flask/helpers.py
    (flask_dir / "helpers.py").write_text("def helper(): pass", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Add helpers"], cwd=repo_dir, check=True)
    c2_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True).stdout.strip()

    # Commit 3 (2022): Restructure move flask/ -> src/flask/
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    subprocess.run(["git", "mv", "flask", "src/flask"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Restructure: move to src/ layout"], cwd=repo_dir, check=True)
    c3_hash = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True).stdout.strip()

    service = HistoryExtractorService()
    result = service.extract_history(repo_dir)

    assert result.history_available is True
    assert result.history_confidence == "high"

    # Verify src/flask/app.py and src/flask/config.py point back to c1_hash, NOT c3_hash
    app_fa = result.file_first_appearance.get("src/flask/app.py")
    assert app_fa is not None
    assert app_fa.commit_hash == c1_hash
    assert app_fa.commit_hash != c3_hash

    config_fa = result.file_first_appearance.get("src/flask/config.py")
    assert config_fa is not None
    assert config_fa.commit_hash == c1_hash

    # Verify src/flask/helpers.py points back to c2_hash, NOT c3_hash
    helpers_fa = result.file_first_appearance.get("src/flask/helpers.py")
    assert helpers_fa is not None
    assert helpers_fa.commit_hash == c2_hash


