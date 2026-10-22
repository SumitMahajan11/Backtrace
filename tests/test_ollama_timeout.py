import os
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import get_settings
from app.sequence.llm_client import get_default_llm_provider


def test_ollama_timeout_default_settings():
    """Verify settings.OLLAMA_TIMEOUT defaults to 120.0."""
    settings = get_settings()
    assert hasattr(settings, "OLLAMA_TIMEOUT")
    assert float(settings.OLLAMA_TIMEOUT) == 120.0


def test_ollama_timeout_no_env_gives_120(monkeypatch):
    """
    Test: when no OLLAMA_TIMEOUT environment variable is set,
    get_default_llm_provider uses settings.OLLAMA_TIMEOUT (120.0).
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_TIMEOUT", raising=False)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "llama3.2:3b"}]}

    recorded_timeout = None
    def mock_create_ollama_provider(model=None, base_url=None, timeout=None):
        nonlocal recorded_timeout
        recorded_timeout = timeout
        return lambda system, user: "mocked"

    with patch("httpx.Client.get", return_value=mock_resp), \
         patch("app.sequence.llm_client.create_ollama_provider", side_effect=mock_create_ollama_provider):
        provider = get_default_llm_provider()
        assert provider is not None
        assert recorded_timeout == 120.0


def test_ollama_timeout_env_300_gives_300(monkeypatch):
    """
    Test: when OLLAMA_TIMEOUT environment variable is set to '300',
    get_default_llm_provider uses 300.0.
    """
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "300")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "llama3.2:3b"}]}

    recorded_timeout = None
    def mock_create_ollama_provider(model=None, base_url=None, timeout=None):
        nonlocal recorded_timeout
        recorded_timeout = timeout
        return lambda system, user: "mocked"

    with patch("httpx.Client.get", return_value=mock_resp), \
         patch("app.sequence.llm_client.create_ollama_provider", side_effect=mock_create_ollama_provider):
        provider = get_default_llm_provider()
        assert provider is not None
        assert recorded_timeout == 300.0
