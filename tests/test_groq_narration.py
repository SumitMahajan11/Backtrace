"""Tests for Groq LLM Narration Provider and Honest UI Labeling."""

import json
import logging
from unittest.mock import patch
import httpx
import pytest

from app.sequence.schema import (
    RepoConfidenceSummary,
    ScoredFileEntry,
    ScoredOrderingResult,
)
from app.sequence.narration_engine import NarrationEngine
from app.sequence.llm_client import create_groq_provider, get_default_llm_provider
from app.ui.components import get_narration_label, get_narration_source, progress_view, report_view
from app.models.db import UserModel


@pytest.fixture
def sample_scored_result() -> ScoredOrderingResult:
    """Fixture providing a deterministic scored ordering result across multiple tiers."""
    files = [
        ScoredFileEntry(
            path="src/config.py",
            tier_index=0,
            confidence="high",
            confidence_reason="topology + verified history",
            tie_break_method="history",
        ),
        ScoredFileEntry(
            path="src/app.py",
            tier_index=1,
            confidence="low",
            confidence_reason="cyclic cluster (circular dependency)",
            tie_break_method="history",
        ),
        ScoredFileEntry(
            path="tests/test_api.py",
            tier_index=2,
            confidence="medium",
            confidence_reason="topology + domain heuristic tie-break",
            tie_break_method="heuristic",
        ),
        ScoredFileEntry(
            path="docs/index.md",
            tier_index=-1,
            confidence="low",
            confidence_reason="isolated, no internal dependency signal",
            tie_break_method="none",
        ),
    ]
    summary = RepoConfidenceSummary(
        high_pct=25.00,
        medium_pct=25.00,
        low_pct=50.00,
        history_available=True,
    )
    return ScoredOrderingResult(
        files=files,
        repo_confidence_summary=summary,
        isolated_files=["docs/index.md"],
        cyclic_files=["src/app.py"],
    )


@pytest.fixture
def mock_user() -> UserModel:
    user = UserModel(id=1, github_id=123, github_username="testdev")
    return user


def test_groq_provider_success(sample_scored_result):
    """Prove: Successful Groq completion returns narration result with source 'llm'."""
    groq_api_response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "# Architectural Reading Guide\n"
                        "### Milestone 1: Configuration\n"
                        "Start by configuring the project environment and base settings modules.\n\n"
                        "### Milestone 2: Core Domain\n"
                        "Next study and assemble the core application modules and handlers.\n\n"
                        "### Milestone 3: Tests\n"
                        "Finally execute the test suite to verify subsystem contracts and prevent regressions."
                    )
                }
            }
        ]
    }

    mock_resp = httpx.Response(
        status_code=200,
        content=json.dumps(groq_api_response).encode("utf-8"),
        request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
    )

    with patch("httpx.Client.post", return_value=mock_resp):
        provider = create_groq_provider(api_key="gsk_test_key_valid_12345")
        engine = NarrationEngine()
        result = engine.generate_narration(sample_scored_result, llm_provider=provider)

        assert result.source == "llm"
        assert get_narration_label(result.source) == "LLM Step-by-Step Narration"
        assert len(result.steps) > 0


def test_groq_provider_timeout_fallback(sample_scored_result, caplog):
    """Prove: Timeout returns template narration with source 'template' without raising."""
    with patch("httpx.Client.post", side_effect=httpx.TimeoutException("Read timed out")):
        provider = create_groq_provider(api_key="gsk_test_key_valid_12345")
        engine = NarrationEngine()
        with caplog.at_level(logging.ERROR):
            result = engine.generate_narration(sample_scored_result, llm_provider=provider)

        assert result.source == "template"
        assert get_narration_label(result.source) == "Step-by-step narration (template)"
        assert len(result.steps) > 0


def test_groq_provider_429_fallback(sample_scored_result, caplog):
    """Prove: 429 Rate Limit returns template narration with source 'template'."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_resp = httpx.Response(status_code=429, request=req, content=b'{"error": "rate_limit_exceeded"}')

    with patch("httpx.Client.post", return_value=mock_resp):
        provider = create_groq_provider(api_key="gsk_test_key_valid_12345")
        engine = NarrationEngine()
        with caplog.at_level(logging.ERROR):
            result = engine.generate_narration(sample_scored_result, llm_provider=provider)

        assert result.source == "template"
        assert get_narration_label(result.source) == "Step-by-step narration (template)"


def test_groq_provider_500_fallback(sample_scored_result, caplog):
    """Prove: 500 Internal Server Error returns template narration with source 'template'."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_resp = httpx.Response(status_code=500, request=req, content=b'{"error": "internal_server_error"}')

    with patch("httpx.Client.post", return_value=mock_resp):
        provider = create_groq_provider(api_key="gsk_test_key_valid_12345")
        engine = NarrationEngine()
        with caplog.at_level(logging.ERROR):
            result = engine.generate_narration(sample_scored_result, llm_provider=provider)

        assert result.source == "template"
        assert get_narration_label(result.source) == "Step-by-step narration (template)"


def test_groq_provider_malformed_json_fallback(sample_scored_result, caplog):
    """Prove: Malformed JSON response returns template narration with source 'template'."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_resp = httpx.Response(status_code=200, request=req, content=b"INVALID JSON {<")

    with patch("httpx.Client.post", return_value=mock_resp):
        provider = create_groq_provider(api_key="gsk_test_key_valid_12345")
        engine = NarrationEngine()
        with caplog.at_level(logging.ERROR):
            result = engine.generate_narration(sample_scored_result, llm_provider=provider)

        assert result.source == "template"
        assert get_narration_label(result.source) == "Step-by-step narration (template)"


def test_groq_provider_missing_key_fallback(sample_scored_result, monkeypatch, caplog):
    """Prove: Missing GROQ_API_KEY returns template narration with source 'template'."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    provider = create_groq_provider(api_key="")
    engine = NarrationEngine()

    with caplog.at_level(logging.ERROR):
        result = engine.generate_narration(sample_scored_result, llm_provider=provider)

    assert result.source == "template"
    assert get_narration_label(result.source) == "Step-by-step narration (template)"


def test_groq_provider_empty_reply_fallback(sample_scored_result, caplog):
    """Prove: Empty replies (missing choices or empty content) return template narration."""
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    empty_cases = [
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": "   \n\t  "}}]},
    ]

    for case in empty_cases:
        mock_resp = httpx.Response(status_code=200, request=req, content=json.dumps(case).encode("utf-8"))
        with patch("httpx.Client.post", return_value=mock_resp):
            provider = create_groq_provider(api_key="gsk_test_key_valid_12345")
            engine = NarrationEngine()
            with caplog.at_level(logging.ERROR):
                result = engine.generate_narration(sample_scored_result, llm_provider=provider)

            assert result.source == "template"
            assert get_narration_label(result.source) == "Step-by-step narration (template)"


def test_no_api_key_or_prompt_logged(sample_scored_result, caplog):
    """Prove: Under no circumstances does any log line contain the secret API key or prompt."""
    secret_key = "gsk_super_confidential_secret_token_999888777"
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    mock_resp = httpx.Response(status_code=429, request=req, content=b'{"error": "rate_limited"}')

    with patch("httpx.Client.post", return_value=mock_resp):
        provider = create_groq_provider(api_key=secret_key)
        engine = NarrationEngine()
        with caplog.at_level(logging.DEBUG):
            result = engine.generate_narration(sample_scored_result, llm_provider=provider)

        assert result.source == "template"
        # Verify secret key is NEVER printed or logged
        assert secret_key not in caplog.text
        # Verify user prompt is not dumped in logs
        assert "Total Scored Files:" not in caplog.text
        for record in caplog.records:
            assert secret_key not in record.getMessage()


def test_env_llm_provider_groq_selection(monkeypatch):
    """Prove: When LLM_PROVIDER=groq, get_default_llm_provider selects Groq provider."""
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_key_123")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")

    provider = get_default_llm_provider()
    assert provider is not None
    assert callable(provider)


def test_narration_label_text_for_both_sources(mock_user):
    """Prove: Label text for both sources in helper and UI rendering."""
    # 1. Pure helper test
    assert get_narration_label("llm") == "LLM Step-by-Step Narration"
    assert get_narration_label("template") == "Step-by-step narration (template)"

    # 2. Progress View test for LLM source
    job_llm = {
        "id": 101,
        "repo_url": "https://github.com/test/repo",
        "repo_name": "repo",
        "status": "completed",
        "narration_source": "llm",
        "graph_data": {"narration_source": "llm"},
    }
    progress_html_llm = progress_view(job_llm, mock_user)
    assert "LLM Step-by-Step Narration" in progress_html_llm
    assert "Step-by-step narration (template)" not in progress_html_llm

    # 3. Progress View test for Template source
    job_tpl = {
        "id": 102,
        "repo_url": "https://github.com/test/repo",
        "repo_name": "repo",
        "status": "completed",
        "narration_source": "template",
        "graph_data": {"narration_source": "template"},
    }
    progress_html_tpl = progress_view(job_tpl, mock_user)
    assert "Step-by-step narration (template)" in progress_html_tpl
    assert "LLM Step-by-Step Narration" not in progress_html_tpl

    # 4. Report View test for LLM source
    report_md_llm = (
        "# Architectural Reverse-Engineering Report: `repo`\n"
        "*Synthesized at: 2026-10-20T12:00:00Z*\n"
        "<!-- narration_source: llm -->\n"
        "## 1. Executive Architecture Overview\n"
        "## 2. Build Order & Confidence Scoring\n"
        "## 3. Step-by-Step Architectural Milestones\n"
        "### Milestone 1: Config\n**[HIGH CONFIDENCE]** -- *Foundational Configuration*\n"
    )
    report_html_llm = report_view(
        job=job_llm,
        raw_markdown=report_md_llm,
        graph_data={"nodes": [], "edges": [], "narration_source": "llm"},
        quiz_data=None,
        current_user=mock_user,
    )
    assert "LLM Step-by-Step Narration" in report_html_llm
    assert "Step-by-step narration (template)" not in report_html_llm

    # 5. Report View test for Template source
    report_md_tpl = (
        "# Architectural Reverse-Engineering Report: `repo`\n"
        "*Synthesized at: 2026-10-20T12:00:00Z*\n"
        "<!-- narration_source: template -->\n"
        "## 1. Executive Architecture Overview\n"
        "## 2. Build Order & Confidence Scoring\n"
        "## 3. Step-by-Step Architectural Milestones\n"
        "### Milestone 1: Config\n**[HIGH CONFIDENCE]** -- *Foundational Configuration*\n"
    )
    report_html_tpl = report_view(
        job=job_tpl,
        raw_markdown=report_md_tpl,
        graph_data={"nodes": [], "edges": [], "narration_source": "template"},
        quiz_data=None,
        current_user=mock_user,
    )
    assert "Step-by-step narration (template)" in report_html_tpl
    assert "LLM Step-by-Step Narration" not in report_html_tpl


def test_first_failure_halts_further_provider_calls(sample_scored_result):
    """Prove (a): First provider failure halts further provider calls in that run."""
    call_count = 0

    def failing_provider(sys_prompt: str, user_prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("Connection refused")

    engine = NarrationEngine()
    # First call: attempts provider, encounters failure, falls back to template
    res1 = engine.generate_narration(sample_scored_result, llm_provider=failing_provider)
    assert call_count == 1
    assert res1.source == "template"

    # Second call in same run: fail-fast skips provider invocation entirely
    res2 = engine.generate_narration(sample_scored_result, llm_provider=failing_provider)
    assert call_count == 1  # No additional provider call made
    assert res2.source == "template"


def test_partial_failure_gives_source_template(sample_scored_result):
    """Prove (b): Partial failure (some provider calls succeed, some fail) gives source 'template'."""
    def ok_provider(sys_prompt: str, user_prompt: str) -> str:
        return (
            "# Architectural Reading Guide\n"
            "### Milestone 1: Configuration\n"
            "Start by configuring the project environment and base settings modules.\n\n"
            "### Milestone 2: Core Domain\n"
            "Next study and assemble the core application modules and handlers.\n\n"
            "### Milestone 3: Tests\n"
            "Finally execute the test suite to verify subsystem contracts and prevent regressions."
        )

    def fail_provider(sys_prompt: str, user_prompt: str) -> str:
        raise httpx.RequestError("Network dropped during provider call")

    engine = NarrationEngine()
    # Call 1 succeeds
    res1 = engine.generate_narration(sample_scored_result, llm_provider=ok_provider)
    assert res1.source == "llm"

    # Call 2 fails in the same run -> partial failure across run's provider calls
    res2 = engine.generate_narration(sample_scored_result, llm_provider=fail_provider)
    assert res2.source == "template"
    assert get_narration_label(res2.source) == "Step-by-step narration (template)"

    # Call 3 in same run: fail-fast activated, also returns template
    res3 = engine.generate_narration(sample_scored_result, llm_provider=ok_provider)
    assert res3.source == "template"
    assert get_narration_label(res3.source) == "Step-by-step narration (template)"


def test_all_calls_succeed_gives_source_llm(sample_scored_result):
    """Prove (c): When all provider calls in the run succeed, source is 'llm'."""
    def ok_provider(sys_prompt: str, user_prompt: str) -> str:
        return (
            "# Architectural Reading Guide\n"
            "### Milestone 1: Configuration\n"
            "Start by configuring the project environment and base settings modules.\n\n"
            "### Milestone 2: Core Domain\n"
            "Next study and assemble the core application modules and handlers.\n\n"
            "### Milestone 3: Tests\n"
            "Finally execute the test suite to verify subsystem contracts and prevent regressions."
        )

    engine = NarrationEngine()
    # Single call succeeds
    res1 = engine.generate_narration(sample_scored_result, llm_provider=ok_provider)
    assert res1.source == "llm"
    assert get_narration_label(res1.source) == "LLM Step-by-Step Narration"

    # Second call in same run also succeeds -> all calls succeed -> source is 'llm'
    res2 = engine.generate_narration(sample_scored_result, llm_provider=ok_provider)
    assert res2.source == "llm"
    assert get_narration_label(res2.source) == "LLM Step-by-Step Narration"


def test_honest_narration_all_milestones_llm(sample_scored_result):
    """Prove: When provider call succeeds and every milestone's prose came from the LLM, source is 'llm'."""
    def all_llm_provider(sys_prompt: str, user_prompt: str) -> str:
        return (
            "# Architectural Reading Guide\n"
            "### Milestone 1: Configuration\n"
            "Start by configuring the project environment and base settings modules.\n\n"
            "### Milestone 2: Core Domain\n"
            "Next study and assemble the core application modules and handlers.\n\n"
            "### Milestone 3: Tests\n"
            "Finally execute the test suite to verify subsystem contracts and prevent regressions."
        )

    engine = NarrationEngine()
    res = engine.generate_narration(sample_scored_result, llm_provider=all_llm_provider)
    assert res.source == "llm"
    assert get_narration_label(res.source) == "LLM Step-by-Step Narration"
    assert len(res.steps) == 3
    # Verify no step fell back
    for s in res.steps:
        assert s.pedagogical_explanation.startswith("**Role:**")


def test_honest_narration_one_milestone_fell_back(sample_scored_result):
    """Prove: If even one milestone fell back to template (e.g. invalid file reference), source is 'template'."""
    def fallback_one_milestone_provider(sys_prompt: str, user_prompt: str) -> str:
        return (
            "# Architectural Reading Guide\n"
            "### Milestone 1: Configuration\n"
            "Start by configuring the project environment and base settings modules.\n\n"
            "### Milestone 2: Core Domain\n"
            "Next configure non_existent_cross_file.py which does not belong here.\n\n"
            "### Milestone 3: Tests\n"
            "Finally execute the test suite to verify subsystem contracts and prevent regressions."
        )

    engine = NarrationEngine()
    res = engine.generate_narration(sample_scored_result, llm_provider=fallback_one_milestone_provider)
    # Because Milestone 2 fell back, overall source must be honest: "template"
    assert res.source == "template"
    assert get_narration_label(res.source) == "Step-by-step narration (template)"


def test_honest_narration_call_failed(sample_scored_result):
    """Prove: If the provider call fails, overall source is 'template'."""
    def failing_provider(sys_prompt: str, user_prompt: str) -> str:
        raise httpx.RequestError("Connection reset by peer")

    engine = NarrationEngine()
    res = engine.generate_narration(sample_scored_result, llm_provider=failing_provider)
    assert res.source == "template"
    assert get_narration_label(res.source) == "Step-by-step narration (template)"


def test_time_budget_switches_to_templates(sample_scored_result):
    """Prove (d): Exceeding the 60s total time budget switches to templates."""
    called = False

    def slow_provider(sys_prompt: str, user_prompt: str) -> str:
        nonlocal called
        called = True
        return "# Guide\n### Milestone 1: Config\nStep 1."

    engine = NarrationEngine(time_budget=60.0)
    # Simulate that prior calls in this run consumed 65 seconds
    engine._elapsed_provider_time = 65.0

    result = engine.generate_narration(sample_scored_result, llm_provider=slow_provider)

    # Provider should be skipped due to exhausted time budget
    assert called is False
    assert result.source == "template"
    assert get_narration_label(result.source) == "Step-by-step narration (template)"


def test_llm_provider_unset_makes_no_httpx_call(monkeypatch):
    """Prove (e): With LLM_PROVIDER unset, get_default_llm_provider returns None with no httpx call."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    with patch("httpx.Client") as mock_client:
        provider = get_default_llm_provider()
        assert provider is None
        mock_client.assert_not_called()


def test_progress_page_shows_neutral_label_for_running_job(mock_user):
    """Prove (f): Progress page shows 'Step-by-step narration' and not 'LLM Step-by-Step Narration' for a running job."""
    running_job = {
        "id": 999,
        "repo_url": "https://github.com/test/repo",
        "repo_name": "repo",
        "status": "running",
        "narration_source": "llm",  # Even if source was prematurely set or speculative
    }
    html = progress_view(running_job, mock_user)
    assert "Step-by-step narration" in html
    assert "LLM Step-by-Step Narration" not in html


def test_narration_time_budget_env_var(monkeypatch):
    """Default is 60; setting the env var NARRATION_TIME_BUDGET_SECONDS to 900 gives 900."""
    monkeypatch.delenv("NARRATION_TIME_BUDGET_SECONDS", raising=False)
    engine_default = NarrationEngine()
    assert engine_default.time_budget == 60

    monkeypatch.setenv("NARRATION_TIME_BUDGET_SECONDS", "900")
    engine_custom = NarrationEngine()
    assert engine_custom.time_budget == 900

