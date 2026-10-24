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
        ("fatal: could not read Username for 'https://github.com': terminal prompts disabled", "access", ACCESS_ERROR),
        ("Repository exceeds size limit", "large", LARGE_ERROR),
        ("too many files", "large", LARGE_ERROR),
        ("IndexError in parser", "generic", GENERIC_ERROR),
        ("tokenizer crashed", "generic", GENERIC_ERROR),
        ("Failed to escape output", "generic", GENERIC_ERROR),
        ("ghostwriter error", "generic", GENERIC_ERROR),
        ("rate limit exceeded", "generic", GENERIC_ERROR),
        ("Failed to reach repository URL. Connection timed out.", "generic", GENERIC_ERROR),
        ("Git operation timed out after 30 seconds.", "generic", GENERIC_ERROR),
        ("Git clone sandbox error", "generic", GENERIC_ERROR),
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
