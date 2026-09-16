"""Stage 6 Layer 11: Edge Case & Resilience Test Suite (Section 6.3).

Asserts graceful degradation and explicit isolation across deliberate edge cases:
1. Large repos: 150+ file boundary enforcement without crashing or silent truncation.
2. Missing git history: zip uploads and shallow clones cleanly degrade to heuristic/topological tie-breaking.
3. Malformed syntax: per-file parse error isolation without pipeline abort.
4. Unsupported languages & uncategorized files: segregated into explicit uncategorized bucket and surfaced in output.
"""

from pathlib import Path
import pytest

from app.models.history import CommitHistoryResult
from app.orchestration.pipeline import PipelineOrchestrator
from app.orchestration.schema import PipelineStage
from app.segmentation.schema import DomainType
from app.sequence.baseline_ordering import BaselineOrderingEngine
from app.sequence.confidence_scoring import ConfidenceScoringEngine
from app.sequence.constrained_tie_breaking import ConstrainedTieBreakerEngine
from app.parser.schema import FileNode, ImportEdge


def test_large_repo_cap_graceful_rejection(tmp_path, monkeypatch):
    """
    Edge Case 1: Large Repos (150+ file boundary)
    1. Constructs a genuinely 155-file git repository on disk.
    2. Runs IngestionService against it to prove ingestion cleanly stops partway through
       walking the repository as soon as the cap is reached, raising IngestionLimitExceededError.
    3. Confirms that sandbox_workspace() cleanly tears down the temporary clone directory
       via safe_rmtree with ZERO partial-state corruption or directory leaks.
    4. Confirms that PipelineOrchestrator gracefully catches the limit and returns success=False
       with structured failure events rather than crashing.
    """
    import subprocess
    import tempfile
    from app.models.ingestion import IngestionLimitExceededError
    from app.services.ingestion import IngestionService

    # 1. Create a genuine 155-file git repository on disk
    repo_dir = tmp_path / "large_origin_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "TestAuthor"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)

    for i in range(155):
        (repo_dir / f"module_{i}.py").write_text(f"# module {i}\ndef run_{i}(): pass\n", encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Commit 155 real files"], cwd=repo_dir, check=True, capture_output=True)

    # 2. Ingest through IngestionService with 150-file cap
    monkeypatch.setattr("app.services.ingestion.validate_github_url", lambda url: ("org", "large_origin_repo"))
    monkeypatch.setattr("app.services.ingestion.validate_ssrf", lambda host: None)
    monkeypatch.setattr("app.services.ingestion.check_repo_reachability", lambda url: None)

    service = IngestionService(max_file_limit=150)

    # Capture active sandboxes before ingestion
    temp_dir_root = Path(tempfile.gettempdir())
    sandboxes_before = set(temp_dir_root.glob("repo_sandbox_*"))

    with pytest.raises(IngestionLimitExceededError) as exc_info:
        service.ingest_repository(str(repo_dir))

    assert "exceeds maximum allowed cap of 150 files" in str(exc_info.value)

    # 3. Verify clean sandbox teardown (no orphan directories or partial clone states left)
    sandboxes_after = set(temp_dir_root.glob("repo_sandbox_*"))
    leaked_sandboxes = sandboxes_after - sandboxes_before
    assert len(leaked_sandboxes) == 0, f"Leaked temporary sandbox directories: {leaked_sandboxes}"

    # 4. Confirm PipelineOrchestrator handles the 155-file boundary gracefully
    orchestrator = PipelineOrchestrator()
    file_paths = [f"src/module_{i}.py" for i in range(155)]
    file_contents = {p: "def run(): pass\n" for p in file_paths}

    result = orchestrator.run_pipeline(
        repo_name="acme/large-monolith",
        file_paths=file_paths,
        file_contents=file_contents,
        enable_rag=False,
    )

    assert result.success is False
    assert result.error is not None
    assert "Repository exceeds v1 cap of 150 files" in result.error
    assert "found 155 files" in result.error

    fail_event = next(e for e in result.events if e.stage == PipelineStage.FAILED)
    assert fail_event.stage_details.get("file_count") == 155
    assert fail_event.stage_details.get("limit") == 150


def test_missing_git_history_graceful_fallback():
    """
    Edge Case 2: Missing Git History (zip uploads / shallow clones)
    Confirms Layer 6's Stage B cleanly degrades to heuristic/topology tie-break
    without erroring, and confidence scoring registers the absence of history.
    """
    stage_a = BaselineOrderingEngine()
    stage_b = ConstrainedTieBreakerEngine()
    stage_c = ConfidenceScoringEngine()

    # Create connected tier where service_a and service_b both import base_util
    node_base = FileNode(path="src/base_util.py", language="python")
    node_a = FileNode(
        path="src/service_a.py",
        language="python",
        imports=[ImportEdge(target="src/base_util.py", resolved=True, source_path="src/service_a.py")],
    )
    node_b = FileNode(
        path="src/service_b.py",
        language="python",
        imports=[ImportEdge(target="src/base_util.py", resolved=True, source_path="src/service_b.py")],
    )

    parsed_files = [node_base, node_a, node_b]
    file_paths = ["src/base_util.py", "src/service_a.py", "src/service_b.py"]
    file_contents = {
        "src/base_util.py": "# base util\n",
        "src/service_a.py": "import src.base_util\n",
        "src/service_b.py": "import src.base_util\n",
    }

    from app.segmentation.engine import SegmentationEngine
    seg_engine = SegmentationEngine()
    seg_result = seg_engine.segment_repository(parsed_files, file_paths)

    a_res = stage_a.compute_baseline_order(
        file_nodes=parsed_files,
        segmentation_result=seg_result,
        all_repo_files=file_paths,
        file_contents=file_contents,
    )

    assert len(a_res.tiers) >= 1

    # Execute Stage B with commit_history=None or history_available=False (simulating zip upload / no git)
    no_history = CommitHistoryResult(
        history_available=False,
        history_confidence="reduced",
        commit_count_processed=0,
        commit_count_total=0,
    )

    b_res = stage_b.refine_baseline_order(
        baseline_result=a_res,
        commit_history=no_history,
        file_contents=file_contents,
    )

    assert b_res is not None
    assert len(b_res.tiers) >= 1
    # Verify all files accounted for
    refined_paths = [e.path for tier in b_res.tiers for e in tier.ordered_files]
    assert set(refined_paths) == set(file_paths)

    # Stage C confidence scoring: should not crash and should record missing history
    c_res = stage_c.compute_confidence_scores(b_res, commit_history=no_history)
    assert c_res is not None
    assert c_res.repo_confidence_summary.history_available is False
    assert len(c_res.files) == len(file_paths)



def test_malformed_syntax_isolation():
    """
    Edge Case 3: Malformed Syntax / Parse Failures
    Confirm a single unparseable file produces a recorded per-file error,
    isolates the bad file, and does NOT crash the pipeline.
    """
    orchestrator = PipelineOrchestrator()

    file_paths = [
        "src/valid1.py",
        "src/valid2.py",
        "src/broken.py",
    ]
    file_contents = {
        "src/valid1.py": "def valid_one(): return 1\n",
        "src/valid2.py": "from src.valid1 import valid_one\ndef valid_two(): return valid_one() + 1\n",
        "src/broken.py": "def invalid_syntax(::\n",
    }

    result = orchestrator.run_pipeline(
        repo_name="acme/partial-syntax-error",
        file_paths=file_paths,
        file_contents=file_contents,
        enable_rag=False,
    )

    # Pipeline MUST succeed despite the single malformed file
    assert result.success is True
    assert result.report is not None

    # Error must be isolated and recorded in parse_errors
    assert len(result.parse_errors) == 1
    err = result.parse_errors[0]
    assert err["path"] == "src/broken.py"
    assert err["language"] == "python"
    assert len(err["error_message"]) > 0

    # Markdown output must surface the isolated error
    assert "## Isolated Parse Warnings" in result.markdown_output
    assert "src/broken.py" in result.markdown_output


def test_unsupported_languages_and_uncategorized_bucket():
    """
    Edge Case 4: Unsupported Languages & Uncategorized Files
    Confirm files with unsupported extensions or unknown conventions are segmented
    into the 'uncategorized' bucket (not silently dropped, not misclassified as 'core')
    and surfaced in output.
    """
    orchestrator = PipelineOrchestrator()

    file_paths = [
        "src/core_service.py",
        "data/dataset.xyz",
        "payload/texture.customblob",
    ]
    file_contents = {
        "src/core_service.py": "class CoreService: pass\n",
        "data/dataset.xyz": "RAW_CUSTOM_DATA_XYZ_STREAM\n",
        "payload/texture.customblob": "CUSTOM_BINARY_BLOB\n",
    }

    result = orchestrator.run_pipeline(
        repo_name="acme/unsupported-files",
        file_paths=file_paths,
        file_contents=file_contents,
        enable_rag=False,
    )

    assert result.success is True

    # Check uncategorized files collection
    assert "data/dataset.xyz" in result.uncategorized_files
    assert "payload/texture.customblob" in result.uncategorized_files
    assert "src/core_service.py" not in result.uncategorized_files

    # Assert uncategorized files are counted as uncategorized in domain breakdown
    domain_counts = result.report.architecture_overview.domain_file_counts
    assert domain_counts.get("uncategorized", 0) == 2

    # Markdown output must clearly surface the uncategorized files
    assert "## Uncategorized & Unsupported Files" in result.markdown_output
    assert "data/dataset.xyz" in result.markdown_output
    assert "payload/texture.customblob" in result.markdown_output


