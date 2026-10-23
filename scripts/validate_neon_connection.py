"""Safe Neon PostgreSQL connection URL validator.

Parses DATABASE_URL using SQLAlchemy's make_url and validates:
- Process-level environment variable presence
- Scheme (postgresql or postgresql+psycopg2)
- Remote Neon hostname (*.neon.tech)
- Database name presence
- SSL mode (sslmode=require)
- Rejection of Docker hostnames ('postgres') and local/placeholder addresses

NEVER prints or leaks usernames, passwords, or credentials.
"""

import os
import sys
from typing import Optional, Tuple
from sqlalchemy.engine import make_url


def validate_database_url(raw_url: Optional[str] = None) -> Tuple[bool, dict, list[str]]:
    """Validates that the provided or environment DATABASE_URL is a valid remote Neon endpoint.

    Returns:
        (is_valid, sanitized_details, error_messages)
    """
    if raw_url is None:
        raw_url = os.environ.get("DATABASE_URL")

    if not raw_url or not raw_url.strip():
        return False, {}, ["DATABASE_URL is not set in the current process environment."]

    try:
        url = make_url(raw_url.strip())
    except Exception as exc:
        return False, {}, [f"Failed to parse connection string with SQLAlchemy URL parser: {exc}"]

    scheme = url.drivername or ""
    host = url.host or ""
    database = url.database or ""
    sslmode = url.query.get("sslmode")

    sanitized = {
        "scheme": scheme,
        "host": host,
        "database": database,
        "sslmode": sslmode,
    }

    errors = []

    # 1. Scheme validation
    if not (scheme.startswith("postgresql") or scheme.startswith("postgres")):
        errors.append(f"Invalid URL scheme '{scheme}'. Expected 'postgresql' or 'postgresql+psycopg2'.")

    # 2. Hostname validation
    if not host:
        errors.append("Database hostname is missing.")
    else:
        host_lower = host.lower()
        if host_lower in ("postgres", "localhost", "127.0.0.1", "0.0.0.0"):
            errors.append(
                f"Unintended local/Docker hostname detected: '{host}'. "
                "For production migrations, a remote Neon PostgreSQL host (*.neon.tech) is required."
            )
        elif not ("neon.tech" in host_lower):
            errors.append(
                f"Target host '{host}' is not a recognized Neon endpoint (*.neon.tech)."
            )

    # 3. Database name validation
    if not database:
        errors.append("Database name is missing.")

    # 4. SSL mode validation
    if sslmode != "require":
        errors.append(
            f"SSL mode must be explicitly configured as 'sslmode=require' (received: '{sslmode}')."
        )

    # 5. Placeholder detection
    raw_lower = raw_url.lower()
    placeholders = (
        "your_",
        "replace_with",
        "<password>",
        "<user>",
        "placeholder",
        "example.com",
    )
    if any(p in raw_lower for p in placeholders):
        errors.append("Connection string contains template placeholder values.")

    is_valid = len(errors) == 0
    return is_valid, sanitized, errors


def main() -> int:
    is_valid, details, errors = validate_database_url()

    if not is_valid:
        sys.stderr.write("=" * 64 + "\n")
        sys.stderr.write("[ERROR] Neon Connection String Validation Failed\n")
        sys.stderr.write("=" * 64 + "\n")
        for err in errors:
            sys.stderr.write(f" - {err}\n")
        if details.get("host") or details.get("scheme"):
            sys.stderr.write("\nSanitized details inspected:\n")
            if details.get("scheme"):
                sys.stderr.write(f"   Scheme:   {details['scheme']}\n")
            if details.get("host"):
                sys.stderr.write(f"   Host:     {details['host']}\n")
            if details.get("database"):
                sys.stderr.write(f"   Database: {details['database']}\n")
            if details.get("sslmode") is not None:
                sys.stderr.write(f"   SSL Mode: {details['sslmode']}\n")
        sys.stderr.write("=" * 64 + "\n")
        return 1

    print("=" * 64)
    print("[SUCCESS] Neon PostgreSQL Connection URL Verified Successfully")
    print("=" * 64)
    print(f"   Scheme:   {details['scheme']}")
    print(f"   Host:     {details['host']}")
    print(f"   Database: {details['database']}")
    print(f"   SSL Mode: {details['sslmode']}")
    print("=" * 64)
    print("Security: Username, password, and secrets remain sanitized and unprinted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
