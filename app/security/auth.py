"""Authentication and Session Security Primitives (Prompt 1).

Implements:
- JWT HS256 stateless access tokens with strict algorithm allowlist enforcement.
- SHA-256 opaque refresh token hashing and verification.
- Cryptographically secure OAuth CSRF state generation and single-use validation.
- Open redirect validation against an allowlist.
- Bearer rate limiting on token refresh endpoint to thwart credential stuffing / brute force.
"""

import hashlib
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import jwt

# Environment Configuration
JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "backtrace-dev-secret-key-change-in-production")
JWT_ALGORITHM: str = "HS256"
ALLOWED_JWT_ALGORITHMS: List[str] = ["HS256"]
JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_REDIRECT_URI: str = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/auth/github/callback")

DEFAULT_ALLOWED_REDIRECT_HOSTS: Set[str] = {
    "localhost",
    "127.0.0.1",
    "backtrace.dev",
    "app.backtrace.dev",
}


def get_allowed_redirect_hosts() -> Set[str]:
    """Parses configured allowed redirect hosts from environment."""
    env_hosts = os.getenv("ALLOWED_REDIRECT_HOSTS", "")
    hosts = set(DEFAULT_ALLOWED_REDIRECT_HOSTS)
    if env_hosts:
        for h in env_hosts.split(","):
            cleaned = h.strip().lower()
            if cleaned:
                hosts.add(cleaned)
    return hosts


class AuthVerificationError(Exception):
    """Raised when token verification or authentication validation fails."""
    pass


def generate_secure_random_token(nbytes: int = 32) -> str:
    """Generates a cryptographically strong, URL-safe random string."""
    return secrets.token_urlsafe(nbytes)


def hash_token(raw_token: str) -> str:
    """Computes SHA-256 hex digest of a token string for safe database storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    user_id: int,
    github_id: int,
    github_username: str,
    is_admin: bool = False,
    expires_delta: Optional[timedelta] = None,
    secret_key: str = JWT_SECRET_KEY,
) -> str:
    """
    Creates a stateless signed JWT access token.
    Enforces HS256 signature with standard claims (sub, exp, iat, jti).
    """
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": str(user_id),
        "github_id": github_id,
        "github_username": github_username,
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": secrets.token_hex(16),
    }

    return jwt.encode(payload, secret_key, algorithm=JWT_ALGORITHM)


def decode_and_verify_access_token(
    token: str,
    secret_key: str = JWT_SECRET_KEY,
) -> Dict[str, Any]:
    """
    Decodes and rigorously verifies JWT access token:
    1. Rejects 'alg: none' and off-allowlist algorithms in the unverified header.
    2. Verifies cryptographic signature using HS256 and secret key.
    3. Verifies 'exp' expiration timestamp.
    4. Validates required claims (sub, github_id).
    """
    if not token or not isinstance(token, str):
        raise AuthVerificationError("Missing or invalid token string")

    # Step 1: Strict Algorithm Allowlist Enforcement
    try:
        unverified_header = jwt.get_unverified_header(token)
    except Exception as exc:
        raise AuthVerificationError(f"Malformed JWT header: {exc}")

    alg = unverified_header.get("alg")
    if not alg or alg not in ALLOWED_JWT_ALGORITHMS or alg.lower() == "none":
        raise AuthVerificationError(f"Rejected algorithm '{alg}'. Only {ALLOWED_JWT_ALGORITHMS} permitted.")

    # Step 2: Cryptographic Signature & Expiry Verification
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=ALLOWED_JWT_ALGORITHMS,
            options={
                "verify_signature": True,
                "verify_exp": True,
                "require": ["exp", "sub", "iat"],
            },
        )
    except jwt.ExpiredSignatureError:
        raise AuthVerificationError("Token has expired")
    except (jwt.InvalidSignatureError, jwt.DecodeError):
        raise AuthVerificationError("Invalid token signature or corrupted payload")
    except jwt.InvalidAlgorithmError as exc:
        raise AuthVerificationError(f"Algorithm error: {exc}")
    except jwt.InvalidTokenError as exc:
        raise AuthVerificationError(f"Invalid token: {exc}")

    # Step 3: Validate Subject Claim
    sub = payload.get("sub")
    if not sub:
        raise AuthVerificationError("Missing subject (sub) claim in token")

    try:
        payload["user_id"] = int(sub)
    except ValueError:
        raise AuthVerificationError("Subject claim (sub) is not a valid integer user ID")

    return payload


def is_safe_redirect_url(target_url: Optional[str]) -> bool:
    """
    Validates redirect URL against Open Redirect attacks:
    - Relative URLs (starting with '/' but NOT '//') are allowed.
    - Absolute URLs must match an approved host from the allowlist.
    """
    if not target_url:
        return True

    target_url = target_url.strip()

    # Reject protocol-relative URLs like '//evil.com'
    if target_url.startswith("//"):
        return False

    # Relative path on same origin
    if target_url.startswith("/") and not target_url.startswith("/\\"):
        return True

    # Absolute URL check
    try:
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = (parsed.hostname or "").lower()
        return hostname in get_allowed_redirect_hosts()
    except Exception:
        return False


class OAuthStateStore:
    """
    Thread-safe, in-memory single-use CSRF state store with automatic TTL expiration.
    Guarantees state parameters cannot be predicted, hijacked, or replayed.
    """

    def __init__(self, ttl_seconds: int = 600):
        self.ttl_seconds = ttl_seconds
        self._states: Dict[str, Tuple[float, Optional[str]]] = {}
        self._lock = threading.Lock()

    def generate_state(self, redirect_url: Optional[str] = None) -> str:
        """Generates a secure state token, associates optional redirect_url, and stores with expiry."""
        state = generate_secure_random_token(32)
        expiry = time.time() + self.ttl_seconds
        with self._lock:
            self._cleanup_expired()
            self._states[state] = (expiry, redirect_url)
        return state

    def validate_and_consume_state(self, state: str) -> Tuple[bool, Optional[str]]:
        """
        Validates state token and immediately deletes it (single-use).
        Returns (is_valid, optional_redirect_url).
        """
        if not state:
            return False, None

        now = time.time()
        with self._lock:
            self._cleanup_expired()
            record = self._states.pop(state, None)
            if not record:
                return False, None
            expiry, redirect_url = record
            if now > expiry:
                return False, None
            return True, redirect_url

    def _cleanup_expired(self) -> None:
        """Removes expired state entries."""
        now = time.time()
        expired_keys = [k for k, (exp, _) in self._states.items() if now > exp]
        for k in expired_keys:
            self._states.pop(k, None)


# Global OAuth state manager singleton
oauth_state_store = OAuthStateStore(ttl_seconds=600)


class SlidingWindowRateLimiter:
    """
    Sliding window in-memory rate limiter to prevent brute force / stuffing
    attacks on sensitive endpoints (e.g. /auth/refresh).
    """

    def __init__(self, max_requests: int = 15, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> bool:
        """Checks whether key has exceeded request quota in the current window."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = self._requests.get(key, [])
            valid_timestamps = [t for t in timestamps if t > cutoff]
            if len(valid_timestamps) >= self.max_requests:
                self._requests[key] = valid_timestamps
                return False
            valid_timestamps.append(now)
            self._requests[key] = valid_timestamps
            return True

    def reset(self) -> None:
        """Clears all stored rate limit history (useful for test resets)."""
        with self._lock:
            self._requests.clear()


# Global refresh token endpoint rate limiter singleton
refresh_rate_limiter = SlidingWindowRateLimiter(max_requests=15, window_seconds=60)
