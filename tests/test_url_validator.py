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
