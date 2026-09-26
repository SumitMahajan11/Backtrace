"""Tests for secret scanner false positive fixes, commit refetch, and UI/mode safety."""

import ast
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.security.secret_scanner import SecretScanner
from app.services.scaffold_generator import ScaffoldGenerator
from app.services.file_content_service import FileContentService, SOURCE_NOT_AVAILABLE_MESSAGE
from app.models.db import RepoModel, AnalysisJobModel, IngestionResultModel, utc_now
from app.ui.components import report_view
from fastapi import HTTPException


def test_reelclaim_false_positives_come_through_unchanged():
    """Verifies that normal code patterns that previously triggered entropy false positives are untouched."""
    scanner = SecretScanner()

    # 1. extraction.py: f-string error message
    extraction_code = '''def load_extraction_system_prompt() -> str:
    if not SYSTEM_PROMPT_FILE.exists():
        legacy_file = Path(__file__).resolve().parent / "prompts" / "claim_extraction.txt"
        if legacy_file.exists():
            with open(legacy_file, "r", encoding="utf-8") as f:
                return f.read()
        raise FileNotFoundError(f"Extraction system prompt not found at {SYSTEM_PROMPT_FILE}")
    with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()'''
    res1, c1 = scanner.scan_and_redact(extraction_code)
    assert c1 == 0
    assert res1 == extraction_code
    assert "[REDACTED]" not in res1

    # 2. TrustGauge.tsx: Tailwind className string
    trust_gauge_code = '''export function TrustGauge() {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider font-semibold font-mono opacity-80">
        Confidence Tier
      </span>
    </div>
  );
}'''
    res2, c2 = scanner.scan_and_redact(trust_gauge_code)
    assert c2 == 0
    assert res2 == trust_gauge_code
    assert "[REDACTED]" not in res2

    # 3. cross_reference.py: User-Agent header
    cross_ref_code = '''HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 (compatible; ReelClaimBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}'''
    res3, c3 = scanner.scan_and_redact(cross_ref_code)
    assert c3 == 0
    assert res3 == cross_ref_code
    assert "[REDACTED]" not in res3

    # 4. models.py: Pydantic Field descriptions
    models_code = '''gemini_api_key: Optional[str] = Field(None, description="Optional per-request Gemini API key for BYOK")

class CheckResponse(BaseModel):
    confidence_tier: ConfidenceTier = Field(..., description="Overall confidence tier: VERIFIED, LIKELY_TRUE, CONTRADICTED, INSUFFICIENT_EVIDENCE")
    coverage_status: Literal["verified", "partially_verified", "unverified_no_data"] = Field(..., description="Overall evidence coverage status")
    summary_label: str = Field(..., description="Explainable, non-defamatory summary of claims vs evidence")'''
    res4, c4 = scanner.scan_and_redact(models_code)
    assert c4 == 0
    assert res4 == models_code
    assert "[REDACTED]" not in res4


def test_real_secrets_are_still_redacted():
    """Verifies that genuine credentials, tokens, and private keys are properly redacted."""
    scanner = SecretScanner()

    dummy_stripe = "sk_" + "live_51AbcDefGhIjKlMnOpQrStUvWxYz123456"
    raw_secrets = f'''
AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
GITHUB_PAT = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
GITHUB_PAT_FINE = "github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz01234567890"
STRIPE_KEY = "{dummy_stripe}"
JWT = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozG4m1e_example_signature_12345"
API_SECRET = "8f4a2b1c9d8e7f6a5b4c3d2e1f0a9b8c"
PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Z3v...
-----END RSA PRIVATE KEY-----"""
'''
    redacted, count = scanner.scan_and_redact(raw_secrets)
    assert count >= 7
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY" not in redacted
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz01234567890" not in redacted
    assert dummy_stripe not in redacted
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "8f4a2b1c9d8e7f6a5b4c3d2e1f0a9b8c" not in redacted
    assert "[REDACTED]" in redacted


def test_fill_the_blanks_does_not_blank_redacted_function():
    """Verifies that Fill the Blanks skips blanking functions that contain a redaction marker."""
    code_with_redaction = '''def setup_client():
    """Initializes external API client."""
    api_key = "[REDACTED]"
    return Client(api_key=api_key)

def process_data(items: list) -> list:
    """Normal processing function without secrets."""
    return [x * 2 for x in items]
'''
    res = ScaffoldGenerator.generate_scaffold(code_with_redaction, language="python", is_redacted=True)
    assert res["has_scaffold"] is True
    # setup_client should NOT be blanked (preserved as-is)
    assert "[REDACTED]" in res["scaffold_code"]
    # process_data should be blanked
    assert "process_data" in [f["name"] for f in res["blanked_functions"]]
    assert "setup_client" not in [f["name"] for f in res["blanked_functions"]]


def test_refetch_uses_repo_commit_hash_when_commit_ref_is_none(monkeypatch):
    """Verifies that re-fetch uses RepoModel.commit_hash if job.commit_ref is None."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Create a repo with a stored commit hash
        repo = RepoModel(
            github_url="https://github.com/org/test-commit-refetch",
            commit_hash="abc123commit456",
            status="complete",
            created_at=utc_now(),
            expires_at=utc_now(),
        )
        session.add(repo)
        session.commit()

        job = AnalysisJobModel(
            user_id=1,
            repo_name="org/test-commit-refetch",
            github_url="https://github.com/org/test-commit-refetch",
            commit_ref=None,  # Job has no explicit commit_ref
            status="completed",
            run_id="run_refetch_test",
        )
        session.add(job)
        session.commit()

        captured_commit_ref = []

        class MockIngestionResult:
            def __init__(self):
                self.file_contents = {"app/main.py": "print('hello')"}
                self.file_tree = []
                self.skipped_items = []
                self.metadata = type("Meta", (), {"head_commit": "abc123commit456", "clone_duration_seconds": 0.1})()

        def mock_ingest(url, commit_ref=None, subpath=None):
            captured_commit_ref.append(commit_ref)
            return MockIngestionResult()

        monkeypatch.setattr("app.services.ingestion.IngestionService.ingest_repository", lambda self, url, commit_ref=None, subpath=None: mock_ingest(url, commit_ref=commit_ref, subpath=subpath))

        fc = FileContentService.get_file_contents_for_job(session=session, job=job, allow_refetch=True)
        assert "app/main.py" in fc
        assert captured_commit_ref == ["abc123commit456"]
    finally:
        session.close()


def test_ui_shows_redaction_notice_and_guess_it_disabling():
    """Verifies that UI components show redaction notice in Just Read It and disable Guess It if no source."""
    job = AnalysisJobModel(
        id=999,
        user_id=1,
        repo_name="org/ui-test",
        github_url="https://github.com/org/ui-test",
        status="completed",
        run_id="run_ui_test",
        markdown_output="# Test Report",
    )

    markdown_report = """# Architectural Reverse-Engineering Report: `org/ui-test`
## 3. Step-by-Step Architectural Milestones

### Milestone 1: Core DB Setup (Tier 1)
**[HIGH CONFIDENCE]** -- *Database Foundation*
**Overview:** Sets up core database models.
**Included Files (1):**
- `app/db.py`
**Key Exported Symbols:** `AuditRecord`
"""

    graph_data = {
        "nodes": [
            {
                "id": "app/db.py",
                "label": "db.py",
                "path": "app/db.py",
                "tier": 1,
                "domain": "backend",
                "confidence": "high",
                "exports": ["AuditRecord"],
            }
        ],
        "edges": [],
    }

    # Case 1: File is in redacted_files
    file_contents_redacted = {
        "app/db.py": 'SECRET = "[REDACTED]"\nclass AuditRecord: pass'
    }

    html_out = report_view(
        job=job,
        raw_markdown=markdown_report,
        graph_data=graph_data,
        quiz_data={"questions": []},
        current_user=None,
        billing_status={"tier": "free"},
        file_contents=file_contents_redacted,
        redacted_files={"app/db.py"},
    )
    assert "Some values were hidden for security" in html_out
    assert "guess-disabled-banner" not in html_out
    assert "Guess It Disabled" not in html_out

    # Case 2: File source missing (empty dict)
    file_contents_missing = {}
    html_out_missing = report_view(
        job=job,
        raw_markdown=markdown_report,
        graph_data=graph_data,
        quiz_data={"questions": []},
        current_user=None,
        billing_status={"tier": "free"},
        file_contents=file_contents_missing,
        redacted_files=set(),
    )
    assert "Guess It Disabled" in html_out_missing


def test_extraction_py_no_false_redaction_notice_or_skip():
    """Verifies that extraction.py (which has literal '[REDACTED]' in re.sub) does not trigger notice or skip Fill the Blanks."""
    extraction_code = '''import re
from pathlib import Path

def sanitize_gemini_error(e: Exception) -> str:
    """Sanitizes sensitive tokens from error message."""
    clean_err = re.sub(r'AIza[A-Za-z0-9_-]{30,60}', '[REDACTED]', str(e))
    return clean_err

def load_extraction_system_prompt() -> str:
    """Loads system prompt."""
    return "prompt_text"
'''
    scanner = SecretScanner()
    redacted_text, count = scanner.scan_and_redact(extraction_code)
    assert count == 0
    assert redacted_text == extraction_code

    # Fill the Blanks should NOT skip functions in extraction.py when is_redacted=False
    scaffold = ScaffoldGenerator.generate_scaffold(
        code=extraction_code,
        language="python",
        file_path="app/extraction.py",
        is_redacted=False,
    )
    assert scaffold["has_scaffold"] is True
    blanked_names = [f["name"] for f in scaffold["blanked_functions"]]
    assert "sanitize_gemini_error" in blanked_names
    assert "load_extraction_system_prompt" in blanked_names
    assert "def sanitize_gemini_error(e: Exception) -> str:" in scaffold["scaffold_code"]

    # UI report_view with redacted_files empty should NOT show the notice bar
    job = AnalysisJobModel(
        id=1001,
        user_id=1,
        repo_name="org/extraction-test",
        github_url="https://github.com/org/extraction-test",
        status="completed",
        run_id="run_extraction_test",
        markdown_output="# Test Report",
    )
    markdown_report = """# Architectural Reverse-Engineering Report: `org/extraction-test`
## 3. Step-by-Step Architectural Milestones

### Milestone 1: Extraction Engine (Tier 1)
**[HIGH CONFIDENCE]** -- *AI Extraction*
**Overview:** Extraction prompt logic.
**Included Files (1):**
- `app/extraction.py`
**Key Exported Symbols:** `sanitize_gemini_error`
"""
    graph_data = {
        "nodes": [
            {
                "id": "app/extraction.py",
                "label": "extraction.py",
                "path": "app/extraction.py",
                "tier": 1,
                "domain": "backend",
                "confidence": "high",
                "exports": ["sanitize_gemini_error"],
            }
        ],
        "edges": [],
    }
    html_out = report_view(
        job=job,
        raw_markdown=markdown_report,
        graph_data=graph_data,
        quiz_data={"questions": []},
        current_user=None,
        billing_status={"tier": "free"},
        file_contents={"app/extraction.py": extraction_code},
        redacted_files=set(),  # Scanner reported 0 redactions for this file
    )
    assert "Some values were hidden for security" not in html_out


def test_multi_commit_and_subpath_isolation():
    """Test: analyze at commit A with default ref, then at B, then subpath variants, then open job A. It must show commit A content."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        url = "https://github.com/test-org/multi-version-repo"
        commit_a = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        commit_b = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

        # 1. Ingest Commit A (default ref, resolved_sha = commit_a)
        FileContentService.persist_file_contents(
            session=session,
            github_url=url,
            file_contents={"app/main.py": "def version(): return 'commit_A_code'"},
            commit_hash=commit_a,
            subpath=None,
        )

        # 2. Create Job A with default ref (commit_ref=None) and resolved_sha=commit_a
        job_a = AnalysisJobModel(
            user_id=1,
            repo_name="test-org/multi-version-repo",
            github_url=url,
            commit_ref=None,  # Default ref
            resolved_sha=commit_a,
            subpath=None,
            status="completed",
            run_id="run_commit_a",
        )
        session.add(job_a)

        # 3. Ingest Commit B (default ref, resolved_sha = commit_b)
        FileContentService.persist_file_contents(
            session=session,
            github_url=url,
            file_contents={"app/main.py": "def version(): return 'commit_B_code'"},
            commit_hash=commit_b,
            subpath=None,
        )

        # 4. Create Job B with default ref (commit_ref=None) and resolved_sha=commit_b
        job_b = AnalysisJobModel(
            user_id=1,
            repo_name="test-org/multi-version-repo",
            github_url=url,
            commit_ref=None,  # Default ref
            resolved_sha=commit_b,
            subpath=None,
            status="completed",
            run_id="run_commit_b",
        )
        session.add(job_b)

        # 5. Ingest Subpath Variant (subpath="packages/api" at commit B)
        FileContentService.persist_file_contents(
            session=session,
            github_url=url,
            file_contents={"packages/api/service.py": "def subpath_api(): return 'api_v2'"},
            commit_hash=commit_b,
            subpath="packages/api",
        )

        # 6. Create Job C with subpath="packages/api"
        job_c = AnalysisJobModel(
            user_id=1,
            repo_name="test-org/multi-version-repo",
            github_url=url,
            commit_ref=None,
            resolved_sha=commit_b,
            subpath="packages/api",
            status="completed",
            run_id="run_commit_c_subpath",
        )
        session.add(job_c)
        session.commit()

        # 7. Open Job A -> Must return Commit A content even though RepoModel has newer Commit B rows
        contents_a = FileContentService.get_file_contents_for_job(session=session, job=job_a, allow_refetch=False)
        assert contents_a.get("app/main.py") == "def version(): return 'commit_A_code'"
        assert "packages/api/service.py" not in contents_a

        # 8. Open Job B -> Must return Commit B content
        contents_b = FileContentService.get_file_contents_for_job(session=session, job=job_b, allow_refetch=False)
        assert contents_b.get("app/main.py") == "def version(): return 'commit_B_code'"

        # 9. Open Job C (subpath variant) -> Must return subpath content
        contents_c = FileContentService.get_file_contents_for_job(session=session, job=job_c, allow_refetch=False)
        assert contents_c.get("packages/api/service.py") == "def subpath_api(): return 'api_v2'"
        assert "app/main.py" not in contents_c
    finally:
        session.close()


def test_subpath_job_without_exact_row_returns_source_not_available():
    """Verifies that a job targeting a subpath with no exact row returns empty dict and SOURCE_NOT_AVAILABLE."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        url = "https://github.com/test-org/subpath-exact-repo"
        commit_sha = "cccccccccccccccccccccccccccccccccccccccc"

        # Ingest only root repo (subpath=None)
        FileContentService.persist_file_contents(
            session=session,
            github_url=url,
            file_contents={"root_file.py": "def root(): return True"},
            commit_hash=commit_sha,
            subpath=None,
        )

        # Job requests subpath "packages/unknown"
        job_subpath = AnalysisJobModel(
            user_id=1,
            repo_name="test-org/subpath-exact-repo",
            github_url=url,
            commit_ref=commit_sha,
            resolved_sha=commit_sha,
            subpath="packages/unknown",
            status="completed",
            run_id="run_unknown_subpath",
        )
        session.add(job_subpath)
        session.commit()

        # Must NOT fallback to root_file.py
        contents = FileContentService.get_file_contents_for_job(session=session, job=job_subpath, allow_refetch=False)
        assert contents == {}

        # Milestone reference code must return SOURCE_NOT_AVAILABLE
        ref_info = FileContentService.get_milestone_reference_code(
            session=session,
            job=job_subpath,
            milestone_tier=1,
            target_file="packages/unknown/service.py",
        )
        assert ref_info["has_real_source"] is False
        assert ref_info["reference_code"] == SOURCE_NOT_AVAILABLE_MESSAGE
    finally:
        session.close()


def test_legacy_job_refetch_does_not_stamp_resolved_sha_and_adds_notice(monkeypatch):
    """Verifies that re-fetching a legacy job (resolved_sha is None) does NOT stamp resolved_sha and marks content."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        url = "https://github.com/test-org/legacy-refetch-repo"
        
        # Legacy job with resolved_sha = None, commit_ref = None
        legacy_job = AnalysisJobModel(
            user_id=1,
            repo_name="test-org/legacy-refetch-repo",
            github_url=url,
            commit_ref=None,
            resolved_sha=None,
            subpath=None,
            status="completed",
            run_id="run_legacy_test",
        )
        session.add(legacy_job)
        session.commit()

        class MockIngestRes:
            def __init__(self):
                self.file_contents = {"main.py": "def hello(): return 'world'"}
                self.file_tree = []
                self.skipped_items = []
                self.metadata = type("Meta", (), {"head_commit": "latest_remote_head_sha_999", "clone_duration_seconds": 0.05})()

        monkeypatch.setattr(
            "app.services.ingestion.IngestionService.ingest_repository",
            lambda self, url, commit_ref=None, subpath=None: MockIngestRes(),
        )

        contents = FileContentService.get_file_contents_for_job(session=session, job=legacy_job, allow_refetch=True)

        # 1. job.resolved_sha must remain None (not stamped with current HEAD)
        assert legacy_job.resolved_sha is None

        # 2. Content must be marked with the notice "current version, may differ from when analyzed"
        assert "main.py" in contents
        assert "may differ from when analyzed" in contents["main.py"]
        assert "def hello(): return 'world'" in contents["main.py"]
    finally:
        session.close()



