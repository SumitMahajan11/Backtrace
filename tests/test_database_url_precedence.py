"""Tests for database URL precedence, Alembic configuration, and safe Neon URL validation."""

import os
import subprocess
import sys
import pytest
from alembic.config import Config
from scripts.validate_neon_connection import validate_database_url


def test_process_database_url_takes_precedence_over_dotenv(tmp_path):
    """Verifies that a process-level DATABASE_URL takes priority over .env without being overwritten."""
    code = (
        "import os\n"
        "from app.db.session import _get_initial_database_url, DATABASE_URL\n"
        "expected = 'postgresql+psycopg2://test_user:secret@ep-test.neon.tech:5432/test_db?sslmode=require'\n"
        "actual = _get_initial_database_url()\n"
        "assert actual == expected, f'Expected {expected}, got {actual}'\n"
        "assert DATABASE_URL == expected, f'Expected {expected}, got {DATABASE_URL}'\n"
    )

    env = dict(os.environ)
    env["DATABASE_URL"] = "postgresql://test_user:secret@ep-test.neon.tech:5432/test_db?sslmode=require"
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("ENVIRONMENT", None)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{current_pythonpath}" if current_pythonpath else repo_root

    res = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert res.returncode == 0, f"Process failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"


def test_alembic_config_escapes_percent_in_database_url():
    """Verifies that percent signs in database URLs (common in URL-encoded passwords) are safely escaped for Alembic."""
    cfg = Config("alembic.ini")
    complex_url = "postgresql+psycopg2://admin:p%40ss%25word%21@ep-neon-123.neon.tech:5432/neondb?sslmode=require"

    # Direct set without escaping would raise ValueError: invalid interpolation syntax
    cfg.set_main_option("sqlalchemy.url", complex_url.replace("%", "%%"))
    retrieved = cfg.get_main_option("sqlalchemy.url")
    assert retrieved == complex_url


def test_validate_neon_connection_success():
    """Validates that a correctly formatted Neon URL passes validation and returns sanitized fields."""
    valid_url = "postgresql://neondb_owner:npg_secret123@ep-cool-fog-123456.us-east-2.aws.neon.tech/neondb?sslmode=require"
    is_valid, details, errors = validate_database_url(valid_url)

    assert is_valid is True
    assert errors == []
    assert details["scheme"] == "postgresql"
    assert details["host"] == "ep-cool-fog-123456.us-east-2.aws.neon.tech"
    assert details["database"] == "neondb"
    assert details["sslmode"] == "require"

    # Confirm secrets are NOT in details
    assert "neondb_owner" not in str(details)
    assert "npg_secret123" not in str(details)


def test_validate_neon_connection_rejects_postgres_docker_hostname():
    """Validates that unintended Docker hostname 'postgres' is rejected."""
    docker_url = "postgresql+psycopg2://backtrace_admin:secret@postgres:5432/backtrace?sslmode=require"
    is_valid, details, errors = validate_database_url(docker_url)

    assert is_valid is False
    assert any("Unintended local/Docker hostname detected: 'postgres'" in e for e in errors)


def test_validate_neon_connection_rejects_localhost():
    """Validates that localhost/127.0.0.1 is rejected when remote Neon is required."""
    local_url = "postgresql://user:pass@127.0.0.1:5432/backtrace?sslmode=require"
    is_valid, details, errors = validate_database_url(local_url)

    assert is_valid is False
    assert any("Unintended local/Docker hostname detected" in e for e in errors)


def test_validate_neon_connection_rejects_missing_sslmode():
    """Validates that URLs missing sslmode=require are rejected."""
    no_ssl = "postgresql://user:pass@ep-cool-fog.neon.tech/neondb"
    is_valid, details, errors = validate_database_url(no_ssl)

    assert is_valid is False
    assert any("sslmode=require" in e for e in errors)


def test_validate_neon_connection_rejects_placeholders():
    """Validates that template placeholder values are rejected."""
    placeholder_url = "postgresql://user:replace_with_password@ep-cool-fog.neon.tech/neondb?sslmode=require"
    is_valid, details, errors = validate_database_url(placeholder_url)

    assert is_valid is False
    assert any("placeholder" in e.lower() for e in errors)
