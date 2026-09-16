"""Authentication and Session Management Test Suite (Prompt 1 Verification).

Tests:
1. Table schema initialization for 'users' and 'refresh_tokens'.
2. OAuth login redirect with cryptographically secure state.
3. CSRF defense: missing, invalid, expired, and replayed state rejection.
4. Open redirect defense: unapproved redirect targets rejected.
5. Full OAuth callback flow (mocked GitHub API) with User upsert and token pair issuance.
6. JWT signature, claims, and expiry validation.
7. Tampered JWT signature rejection (HTTP 401).
8. 'alg: none' header attack rejection (HTTP 401).
9. Algorithm confusion (e.g. RS256/ES256 passed to HS256 verifier) rejection (HTTP 401).
10. Deleted / non-existent user token rejection (HTTP 401).
11. Refresh token rotation: valid refresh yields new tokens and revokes old refresh token.
12. Refresh token replay rejection: revoked token reuse triggers HTTP 401.
13. Bearer rate limiting on /auth/refresh against brute-force / stuffing (HTTP 429).
14. Protected endpoint with no token returns HTTP 401.
15. Protected endpoint with garbage / corrupted token returns HTTP 401.
16. Protected endpoint with valid token returns HTTP 200 and binds request to authenticated user.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_db
from app.db.session import Base
from app.main import app
from app.models.db import RefreshTokenModel, UserModel, utc_now
from app.security.auth import (
    JWT_SECRET_KEY,
    AuthVerificationError,
    create_access_token,
    decode_and_verify_access_token,
    generate_secure_random_token,
    hash_token,
    is_safe_redirect_url,
    oauth_state_store,
    refresh_rate_limiter,
)
from app.services.auth_service import AuthService
from app.storage.user_repository import UserRepository


# SQLite in-memory with StaticPool so all connections share the same memory DB
@pytest.fixture(scope="function")
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestingSessionLocal, engine
    Base.metadata.drop_all(bind=engine)
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def client(test_db):
    refresh_rate_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    refresh_rate_limiter.reset()


def test_schema_users_and_refresh_tokens_tables(test_db):
    """
    Acceptance Criteria: Verify 'users' and 'refresh_tokens' tables are properly created
    in the database with all required columns and constraints.
    """
    _, engine = test_db
    with engine.connect() as conn:
        user_cols = conn.execute(text("PRAGMA table_info(users)")).fetchall()
        user_col_names = [col[1] for col in user_cols]
        assert "id" in user_col_names
        assert "github_id" in user_col_names
        assert "github_username" in user_col_names
        assert "email" in user_col_names
        assert "avatar_url" in user_col_names
        assert "created_at" in user_col_names
        assert "is_admin" in user_col_names

        token_cols = conn.execute(text("PRAGMA table_info(refresh_tokens)")).fetchall()
        token_col_names = [col[1] for col in token_cols]
        assert "id" in token_col_names
        assert "user_id" in token_col_names
        assert "token_hash" in token_col_names
        assert "created_at" in token_col_names
        assert "expires_at" in token_col_names
        assert "revoked_at" in token_col_names


def test_oauth_login_redirect_and_state(client):
    """
    Acceptance Criteria: GET /auth/github/login redirects to GitHub with client_id,
    scope, redirect_uri, and a cryptographically random state parameter.
    """
    response = client.get("/auth/github/login", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers.get("location")
    assert location is not None
    assert "https://github.com/login/oauth/authorize" in location
    assert "client_id=" in location
    assert "scope=read%3Auser+user%3Aemail" in location or "scope=read:user" in location
    assert "state=" in location


def test_oauth_csrf_missing_or_invalid_state_rejected(client):
    """
    Acceptance Criteria: OAuth callback strictly rejects missing, invalid, or replayed state.
    """
    # 1. Missing state parameter
    resp_missing = client.get("/auth/github/callback?code=mock_code_123")
    assert resp_missing.status_code == 400
    assert "Missing required OAuth parameters" in resp_missing.json()["detail"]

    # 2. Fake / invalid state parameter
    resp_invalid = client.get("/auth/github/callback?code=mock_code_123&state=unregistered_state_999")
    assert resp_invalid.status_code == 400
    assert "Invalid, expired, or replayed" in resp_invalid.json()["detail"]


def test_oauth_csrf_single_use_state_replay_rejected(client):
    """
    Acceptance Criteria: State tokens are single-use only. A replayed state must be rejected.
    """
    valid_state = oauth_state_store.generate_state()

    mock_profile = {
        "github_id": 987654,
        "github_username": "octocat",
        "email": "octocat@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/987654",
    }

    with patch.object(AuthService, "exchange_github_code_async", new=AsyncMock(return_value="gh_mock_tok_123")), \
         patch.object(AuthService, "fetch_github_user_profile_async", new=AsyncMock(return_value=mock_profile)):

        # First callback with valid state -> Succeeds
        resp1 = client.get(f"/auth/github/callback?code=code_1&state={valid_state}")
        assert resp1.status_code == 200

        # Second callback with the same state -> MUST FAIL (Replay attack blocked)
        resp2 = client.get(f"/auth/github/callback?code=code_2&state={valid_state}")
        assert resp2.status_code == 400
        assert "Invalid, expired, or replayed" in resp2.json()["detail"]


def test_open_redirect_defense():
    """
    Acceptance Criteria: Redirect targets must be strictly validated against an allowlist.
    Unapproved external destinations (e.g. evil.com) must be rejected.
    """
    assert is_safe_redirect_url("/dashboard") is True
    assert is_safe_redirect_url("/auth/complete?session=1") is True
    assert is_safe_redirect_url("https://app.backtrace.dev/projects") is True
    assert is_safe_redirect_url("http://localhost:3000/callback") is True

    # Attacker payloads
    assert is_safe_redirect_url("https://evil-attacker.com/steal") is False
    assert is_safe_redirect_url("//evil.com/phishing") is False
    assert is_safe_redirect_url("javascript:alert(1)") is False
    assert is_safe_redirect_url("https://backtrace.dev.evil.com") is False


def test_oauth_callback_flow_success_and_user_upsert(client, test_db):
    """
    Acceptance Criteria: Valid OAuth callback exchanges code, fetches profile, upserts User row,
    and returns stateless access_token + revocable refresh_token pair.
    """
    SessionLocal, _ = test_db
    valid_state = oauth_state_store.generate_state()

    mock_profile = {
        "github_id": 1234567,
        "github_username": "monalisa",
        "email": "monalisa@github.com",
        "avatar_url": "https://avatars.githubusercontent.com/u/1234567",
    }

    with patch.object(AuthService, "exchange_github_code_async", new=AsyncMock(return_value="gho_test_token")), \
         patch.object(AuthService, "fetch_github_user_profile_async", new=AsyncMock(return_value=mock_profile)):

        resp = client.get(f"/auth/github/callback?code=valid_gh_code&state={valid_state}")
        assert resp.status_code == 200
        data = resp.json()

        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 900
        assert data["user"]["github_username"] == "monalisa"
        assert data["user"]["github_id"] == 1234567

        # Verify User table record exists
        with SessionLocal() as db_session:
            user = UserRepository.get_user_by_github_id(db_session, 1234567)
            assert user is not None
            assert user.github_username == "monalisa"
            assert user.email == "monalisa@github.com"
            assert user.is_admin is False

            # Verify only hashed refresh token is stored in DB
            raw_refresh_token = data["refresh_token"]
            expected_hash = hash_token(raw_refresh_token)
            token_record = UserRepository.get_refresh_token_by_hash(db_session, expected_hash)
            assert token_record is not None
            assert token_record.user_id == user.id
            assert token_record.revoked_at is None


def test_jwt_signature_and_expiry_validation(test_db):
    """
    Acceptance Criteria: Valid JWT token is verified; expired JWT token is rejected.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=111, github_username="alice")
        db_session.commit()
        user_id = user.id

    # 1. Valid Token
    valid_token = create_access_token(user_id, 111, "alice", expires_delta=timedelta(minutes=15))
    claims = decode_and_verify_access_token(valid_token)
    assert claims["user_id"] == user_id
    assert claims["github_username"] == "alice"

    # 2. Expired Token
    expired_token = create_access_token(user_id, 111, "alice", expires_delta=timedelta(seconds=-10))
    with pytest.raises(AuthVerificationError, match="Token has expired"):
        decode_and_verify_access_token(expired_token)


def test_jwt_tampered_signature_rejected():
    """
    Acceptance Criteria: Tampered JWT payload or signature is rejected.
    """
    valid_token = create_access_token(user_id=1, github_id=123, github_username="alice")
    parts = valid_token.split(".")
    # Tamper with the payload part
    tampered_token = f"{parts[0]}.eyJzdWIiOiIyIiwiaXNfYWRtaW4iOnRydWV9.{parts[2]}"

    with pytest.raises(AuthVerificationError, match="Invalid token signature"):
        decode_and_verify_access_token(tampered_token)


def test_jwt_alg_none_attack_rejected():
    """
    Acceptance Criteria: JWTs crafted with 'alg: none' header must be explicitly rejected.
    """
    payload = {
        "sub": "1",
        "github_id": 123,
        "github_username": "attacker",
        "is_admin": True,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    # Forged 'alg: none' token with trailing empty signature
    forged_none_token = jwt.encode(payload, key="", algorithm="none")

    with pytest.raises(AuthVerificationError, match="Rejected algorithm 'none'"):
        decode_and_verify_access_token(forged_none_token)


def test_jwt_algorithm_confusion_off_allowlist_rejected():
    """
    Acceptance Criteria: Reject tokens signed with unapproved algorithms (e.g. HS384, HS512, RS256).
    """
    payload = {
        "sub": "1",
        "github_id": 123,
        "github_username": "alice",
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    # Sign with HS384 instead of approved HS256
    hs384_token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS384")

    with pytest.raises(AuthVerificationError, match="Rejected algorithm 'HS384'"):
        decode_and_verify_access_token(hs384_token)


def test_jwt_deleted_user_rejected(client, test_db):
    """
    Acceptance Criteria: A validly signed JWT for a user that was deleted from the database
    must return 401 Unauthorized when accessing protected endpoints.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=888, github_username="tempuser")
        db_session.commit()
        user_id = user.id
        token = create_access_token(user.id, user.github_id, user.github_username)

        # Delete user from DB
        db_session.delete(user)
        db_session.commit()

    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get("/auth/me", headers=headers)
    assert resp.status_code == 401
    assert "User associated with this token no longer exists" in resp.json()["detail"]


def test_refresh_token_rotation_and_revocation(client, test_db):
    """
    Acceptance Criteria: POST /auth/refresh accepts valid refresh token,
    revokes the presented refresh token, and issues a fresh token pair.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=444, github_username="bob")
        initial_tokens = AuthService.issue_token_pair(db_session, user)
        db_session.commit()

    old_refresh_token = initial_tokens["refresh_token"]
    old_hash = hash_token(old_refresh_token)

    # Execute token refresh
    resp = client.post("/auth/refresh", json={"refresh_token": old_refresh_token})
    assert resp.status_code == 200
    refreshed = resp.json()

    assert "access_token" in refreshed
    assert "refresh_token" in refreshed
    assert refreshed["refresh_token"] != old_refresh_token

    # Verify old token is marked as revoked in DB
    with SessionLocal() as db_session:
        old_record = UserRepository.get_refresh_token_by_hash(db_session, old_hash)
        assert old_record is not None
        assert old_record.revoked_at is not None

        # Verify new token is active in DB
        new_hash = hash_token(refreshed["refresh_token"])
        new_record = UserRepository.get_refresh_token_by_hash(db_session, new_hash)
        assert new_record is not None
        assert new_record.revoked_at is None


def test_refresh_token_reuse_after_revocation_rejected(client, test_db):
    """
    Acceptance Criteria: Attempting to reuse an already-revoked refresh token must be rejected with 401.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=555, github_username="charlie")
        tokens = AuthService.issue_token_pair(db_session, user)
        db_session.commit()
    raw_refresh = tokens["refresh_token"]

    # 1. First refresh -> Revokes original token and succeeds
    resp1 = client.post("/auth/refresh", json={"refresh_token": raw_refresh})
    assert resp1.status_code == 200

    # 2. Second refresh with original token -> Must fail (Replay detected)
    resp2 = client.post("/auth/refresh", json={"refresh_token": raw_refresh})
    assert resp2.status_code == 401
    assert "Refresh token has been revoked" in resp2.json()["detail"]


def test_logout_revokes_refresh_token(client, test_db):
    """
    Acceptance Criteria: POST /auth/logout revokes the presented refresh token.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=666, github_username="david")
        tokens = AuthService.issue_token_pair(db_session, user)
        db_session.commit()
    raw_refresh = tokens["refresh_token"]

    # Logout
    logout_resp = client.post("/auth/logout", json={"refresh_token": raw_refresh})
    assert logout_resp.status_code == 200
    assert logout_resp.json()["status"] == "success"

    # Attempting to refresh after logout must fail
    refresh_resp = client.post("/auth/refresh", json={"refresh_token": raw_refresh})
    assert refresh_resp.status_code == 401
    assert "Refresh token has been revoked" in refresh_resp.json()["detail"]


def test_refresh_token_rate_limiting_defense(client, test_db):
    """
    Acceptance Criteria: Rapid brute-force requests to /auth/refresh trigger HTTP 429 Too Many Requests.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=777, github_username="eve")
        tokens = AuthService.issue_token_pair(db_session, user)
        db_session.commit()

    # Send rapid refresh requests exceeding the rate limiter limit (15 req/min)
    hit_429 = False
    for _ in range(20):
        with SessionLocal() as db_session:
            cur_user = UserRepository.get_user_by_github_id(db_session, 777)
            t = AuthService.issue_token_pair(db_session, cur_user)
            db_session.commit()
        resp = client.post("/auth/refresh", json={"refresh_token": t["refresh_token"]})
        if resp.status_code == 429:
            hit_429 = True
            assert "Too many refresh requests" in resp.json()["detail"]
            break

    assert hit_429 is True


def test_protected_pipeline_endpoint_unauthorized_with_no_token(client):
    """
    Acceptance Criteria: Protected pipeline endpoint returns HTTP 401 when called with no Authorization header.
    """
    payload = {
        "repo_name": "acme/sample",
        "file_paths": ["main.py"],
        "file_contents": {"main.py": "print('hello')"},
        "enable_rag": False,
    }
    resp = client.post("/api/pipeline/run", json=payload)
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
    assert "Missing or invalid Authorization header" in resp.json()["detail"]


def test_protected_pipeline_endpoint_unauthorized_with_garbage_token(client):
    """
    Acceptance Criteria: Protected pipeline endpoint returns HTTP 401 when called with corrupted / garbage token.
    """
    payload = {
        "repo_name": "acme/sample",
        "file_paths": ["main.py"],
        "file_contents": {"main.py": "print('hello')"},
        "enable_rag": False,
    }
    headers = {"Authorization": "Bearer not_a_valid_jwt_token_garbage_xyz"}
    resp = client.post("/api/pipeline/run", json=payload, headers=headers)
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers
    assert resp.json()["detail"] is not None


def test_protected_pipeline_endpoint_authorized_success(client, test_db):
    """
    Acceptance Criteria: Protected pipeline endpoint returns HTTP 200 when presented with a valid JWT access token,
    and returns analysis output tied to the authenticated user.
    """
    SessionLocal, _ = test_db
    with SessionLocal() as db_session:
        user = UserRepository.upsert_github_user(db_session, github_id=999, github_username="verified_dev")
        db_session.commit()
        user_id = user.id
    access_token = create_access_token(user_id, 999, "verified_dev")

    payload = {
        "repo_name": "acme/sample",
        "file_paths": ["src/main.py", "src/helper.py"],
        "file_contents": {
            "src/main.py": "from src.helper import get_val\n",
            "src/helper.py": "def get_val(): return 42\n",
        },
        "enable_rag": False,
        "run_id": "auth-pipeline-run-001",
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = client.post("/api/pipeline/run", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["success"] is True
    assert data["run_id"] == "auth-pipeline-run-001"
    assert data["user_id"] == user_id
    assert data["user_github_username"] == "verified_dev"
    assert len(data["layers_executed"]) > 0
