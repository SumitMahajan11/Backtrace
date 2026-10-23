"""Unit tests for URL and SSRF validation."""

import pytest
from app.models.ingestion import InvalidURLError, SSRFError
from app.utils.url_validator import validate_github_url, validate_ssrf


def test_valid_github_urls():
    owner, repo = validate_github_url("https://github.com/torvalds/linux")
    assert owner == "torvalds"
    assert repo == "linux"

    owner, repo = validate_github_url("https://github.com/python/cpython.git")
    assert owner == "python"
    assert repo == "cpython"

    owner, repo = validate_github_url("https://github.com/my-org/my_repo-name/")
    assert owner == "my-org"
    assert repo == "my_repo-name"


def test_invalid_scheme_and_domain():
    with pytest.raises(InvalidURLError, match="Only HTTPS protocol is allowed"):
        validate_github_url("http://github.com/owner/repo")

    with pytest.raises(InvalidURLError, match="Only public github.com URLs are supported"):
        validate_github_url("https://gitlab.com/owner/repo")

    with pytest.raises(InvalidURLError, match="Only public github.com URLs are supported"):
        validate_github_url("https://malicious-github.com/owner/repo")


def test_embedded_credentials():
    with pytest.raises(InvalidURLError, match="embedded credentials"):
        validate_github_url("https://user:pass@github.com/owner/repo")


def test_non_standard_ports():
    with pytest.raises(InvalidURLError, match="Non-standard ports"):
        validate_github_url("https://github.com:8443/owner/repo")


def test_malformed_urls():
    with pytest.raises(InvalidURLError):
        validate_github_url("not_a_url")

    with pytest.raises(InvalidURLError):
        validate_github_url("https://github.com/owner")


def test_ssrf_validation():
    # Public domain should pass SSRF check (mocking or resolving github.com)
    validate_ssrf("github.com")

    # Private IP resolving domains / loopback test
    with pytest.raises(SSRFError):
        validate_ssrf("localhost")


def test_check_repo_reachability_sanitizes_request_error(monkeypatch):
    """
    Verifies that network/request errors in check_repo_reachability do not expose
    internal exception details (such as proxy IPs, socket errors, errno) to callers.
    """
    import httpx
    from app.utils.url_validator import check_repo_reachability

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def head(self, *args, **kwargs):
            raise httpx.ConnectError("Connection refused to internal proxy 10.0.0.1:8080: [Errno 111]")

    monkeypatch.setattr(httpx, "Client", MockClient)

    with pytest.raises(InvalidURLError) as exc_info:
        check_repo_reachability("https://github.com/owner/repo")

    msg = str(exc_info.value)
    assert "10.0.0.1" not in msg
    assert "Connection refused" not in msg
    assert "[Errno 111]" not in msg
    assert "ConnectError" not in msg
    assert msg == "Failed to reach repository URL. Verify the repository is publicly accessible."

