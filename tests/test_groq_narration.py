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
                        "Start with configuration.\n\n"
                        "### Milestone 2: Core Domain\n"
                        "Next set up core app.\n\n"
                        "### Milestone 3: Tests\n"
                        "Finally run tests."
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
