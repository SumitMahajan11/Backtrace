import pytest
from app.core.failure_reason import (
    failure_reason,
    map_failure_reason,
    ACCESS_ERROR,
    LARGE_ERROR,
    GENERIC_ERROR,
)


@pytest.mark.parametrize(
    "raw_input,expected_class,expected_sentence",
    [
        ("Repository not found (404)", "access", ACCESS_ERROR),
        ("Authentication failed", "access", ACCESS_ERROR),
        ("could not read Username for 'https://github.com'", "access", ACCESS_ERROR),
        ("Repository at 'https://github.com/org/priv' is not publicly reachable (HTTP 404).", "access", ACCESS_ERROR),
        ("Repository at 'https://github.com/o/r' is not publicly reachable (HTTP 404).", "access", ACCESS_ERROR),
        ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "access", ACCESS_ERROR),
        ("Repository exceeds size limit", "large", LARGE_ERROR),
        ("too many files", "large", LARGE_ERROR),
        ("IndexError in parser", "generic", GENERIC_ERROR),
        ("tokenizer crashed", "generic", GENERIC_ERROR),
        ("Failed to escape output", "generic", GENERIC_ERROR),
        ("ghostwriter error", "generic", GENERIC_ERROR),
        ("rate limit exceeded", "generic", GENERIC_ERROR),
        ("Failed to reach repository URL. Connection timed out.", "generic", GENERIC_ERROR),
        ("Failed to reach repository URL. Verify the repository is publicly accessible.", "generic", GENERIC_ERROR),
        ("Failed while cloning repository into analysis sandbox.", "generic", GENERIC_ERROR),
        ("Git operation timed out after 30 seconds.", "generic", GENERIC_ERROR),
        ("fatal: could not resolve host: github.com", "generic", GENERIC_ERROR),
        ("Unexpected token in parser", "generic", GENERIC_ERROR),
        ("Module not found: utils", "generic", GENERIC_ERROR),
        ("IndexError at line 404", "generic", GENERIC_ERROR),
        ("private method crashed", "generic", GENERIC_ERROR),
        ("Git clone sandbox error", "generic", GENERIC_ERROR),
        ("Git clone failed: No space left on device.", "generic", GENERIC_ERROR),
        ("", "generic", GENERIC_ERROR),
        (None, "generic", GENERIC_ERROR),
    ],
)
def test_failure_reason_classification(raw_input, expected_class, expected_sentence):
    result = failure_reason(raw_input)
    assert result == expected_sentence
    # Also verify map_failure_reason alias
    assert map_failure_reason(raw_input) == expected_sentence

    if expected_class == "access":
        assert result == "We couldn't access this repository (it may be private or the link is wrong)"
    elif expected_class == "large":
        assert result == "The repository is too large"
    else:
        assert result == "Something went wrong on our side"


@pytest.mark.parametrize(
    "status_code,message,expected",
    [
        (404, "Not Found", ACCESS_ERROR),
        (401, "Bad credentials", ACCESS_ERROR),
        (403, "Forbidden", ACCESS_ERROR),
        (403, "API rate limit exceeded", "GitHub is busy right now. Try again in a few minutes."),
        (429, "Too Many Requests", "GitHub is busy right now. Try again in a few minutes."),
        (500, "Internal Server Error", GENERIC_ERROR),
    ],
)
def test_map_github_api_error_parametrized(status_code, message, expected):
    from app.models.ingestion import GitHubAPIError
    from app.core.failure_reason import map_github_api_error, GITHUB_BUSY_ERROR

    err = GitHubAPIError(message, status_code=status_code)
    assert map_github_api_error(err) == expected
    assert map_github_api_error(status_code, message) == expected

