"""Authentication Service orchestrating GitHub OAuth and Session Tokens."""

import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.models.db import RefreshTokenModel, UserModel, utc_now
from app.security.auth import (
    GITHUB_CLIENT_ID,
    GITHUB_CLIENT_SECRET,
    GITHUB_REDIRECT_URI,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    generate_secure_random_token,
    hash_token,
    is_safe_redirect_url,
    oauth_state_store,
)
from app.storage.user_repository import UserRepository


class AuthServiceError(Exception):
    """Base exception for authentication service failures."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthService:
    """Orchestrates GitHub OAuth lifecycle, token issuance, rotation, and revocation."""

    GITHUB_AUTHORIZE_URL: str = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL: str = "https://github.com/login/oauth/access_token"
    GITHUB_USER_API_URL: str = "https://api.github.com/user"
    GITHUB_EMAILS_API_URL: str = "https://api.github.com/user/emails"

    @classmethod
    def get_login_redirect_url(
        cls,
        redirect_target: Optional[str] = None,
        client_id: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> str:
        """
        Builds the GitHub OAuth authorization URL with a cryptographically secure,
        single-use CSRF state token.
        """
        from app.core.config import get_settings
        settings = get_settings()
        c_id = client_id or settings.GITHUB_CLIENT_ID or GITHUB_CLIENT_ID
        r_uri = redirect_uri or settings.GITHUB_REDIRECT_URI or GITHUB_REDIRECT_URI

        # Validate open redirect safety on desired destination
        if redirect_target and not is_safe_redirect_url(redirect_target):
            raise AuthServiceError("Invalid or untrusted redirect target URL", status_code=400)

        state = oauth_state_store.generate_state(redirect_url=redirect_target)

        params = {
            "client_id": c_id,
            "redirect_uri": r_uri,
            "scope": "read:user user:email",
            "state": state,
        }
        return f"{cls.GITHUB_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    @classmethod
    async def exchange_github_code_async(
        cls,
        code: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        redirect_uri: Optional[str] = None,
    ) -> str:
        """Exchanges GitHub authorization code for GitHub OAuth access token."""
        from app.core.config import get_settings
        settings = get_settings()
        c_id = client_id or settings.GITHUB_CLIENT_ID or GITHUB_CLIENT_ID
        c_secret = client_secret or settings.GITHUB_CLIENT_SECRET or GITHUB_CLIENT_SECRET
        r_uri = redirect_uri or settings.GITHUB_REDIRECT_URI or GITHUB_REDIRECT_URI

        payload = {
            "client_id": c_id,
            "client_secret": c_secret,
            "code": code,
            "redirect_uri": r_uri,
        }
        headers = {"Accept": "application/json"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(cls.GITHUB_TOKEN_URL, json=payload, headers=headers)
            if resp.status_code != 200:
                raise AuthServiceError("Failed to communicate with GitHub OAuth token endpoint", status_code=502)

            data = resp.json()
            if "error" in data:
                err_desc = data.get("error_description", data.get("error"))
                raise AuthServiceError(f"GitHub OAuth error: {err_desc}", status_code=400)

            access_token = data.get("access_token")
            if not access_token:
                raise AuthServiceError("GitHub did not return an access token", status_code=502)
            return access_token

    @classmethod
    async def fetch_github_user_profile_async(cls, github_token: str) -> Dict[str, Any]:
        """Fetches user profile and primary verified email from GitHub API."""
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Backtrace-Auth/1.0",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(cls.GITHUB_USER_API_URL, headers=headers)
            if resp.status_code != 200:
                raise AuthServiceError("Failed to fetch user profile from GitHub", status_code=502)
            user_data = resp.json()

            github_id = user_data.get("id")
            username = user_data.get("login")
            email = user_data.get("email")
            avatar_url = user_data.get("avatar_url")

            if not github_id or not username:
                raise AuthServiceError("GitHub profile missing required user identifiers", status_code=502)

            # If primary email is private in profile, fetch emails endpoint
            if not email:
                try:
                    email_resp = await client.get(cls.GITHUB_EMAILS_API_URL, headers=headers)
                    if email_resp.status_code == 200:
                        emails_list = email_resp.json()
                        for item in emails_list:
                            if item.get("primary") and item.get("verified"):
                                email = item.get("email")
                                break
                        if not email and emails_list:
                            email = emails_list[0].get("email")
                except Exception:
                    pass  # Non-fatal if emails endpoint fails

            return {
                "github_id": int(github_id),
                "github_username": str(username),
                "email": email,
                "avatar_url": avatar_url,
            }

    @classmethod
    def issue_token_pair(cls, session: Session, user: UserModel) -> Dict[str, Any]:
        """
        Issues short-lived JWT access token and creates server-side revocable refresh token.
        Returns token pair with metadata.
        """
        # 1. Stateless Access Token (15 min)
        access_token = create_access_token(
            user_id=user.id,
            github_id=user.github_id,
            github_username=user.github_username,
            is_admin=user.is_admin,
        )

        # 2. Opaque Refresh Token (30 days)
        raw_refresh_token = generate_secure_random_token(64)
        token_hash = hash_token(raw_refresh_token)
        expires_at = utc_now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        UserRepository.create_refresh_token(
            session=session,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh_token,
            "token_type": "bearer",
            "expires_in": 900,  # 15 minutes in seconds
            "user": {
                "id": user.id,
                "github_id": user.github_id,
                "github_username": user.github_username,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "is_admin": user.is_admin,
                "created_at": user.created_at.isoformat(),
            },
        }

    @classmethod
    async def process_oauth_callback(
        cls,
        code: str,
        state: str,
        session: Session,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """
        Processes OAuth callback:
        1. Validates and single-use consumes CSRF state.
        2. Exchanges code for GitHub access token.
        3. Fetches user profile.
        4. Upserts User row.
        5. Issues token pair.
        Returns (token_pair_dict, optional_post_login_redirect_url).
        """
        if not state:
            raise AuthServiceError("Missing OAuth state parameter", status_code=400)

        is_valid_state, redirect_target = oauth_state_store.validate_and_consume_state(state)
        if not is_valid_state:
            raise AuthServiceError("Invalid, expired, or replayed OAuth state parameter", status_code=400)

        if not code:
            raise AuthServiceError("Missing OAuth code parameter", status_code=400)

        github_access_token = await cls.exchange_github_code_async(code)
        profile = await cls.fetch_github_user_profile_async(github_access_token)

        existing_user = UserRepository.get_user_by_github_id(session, profile["github_id"])
        is_new_user = existing_user is None

        user = UserRepository.upsert_github_user(
            session=session,
            github_id=profile["github_id"],
            github_username=profile["github_username"],
            email=profile.get("email"),
            avatar_url=profile.get("avatar_url"),
        )

        if is_new_user:
            from app.monitoring.posthog import analytics
            analytics.capture_user_signup(user_id=user.id, is_admin=user.is_admin)

        tokens = cls.issue_token_pair(session, user)
        return tokens, redirect_target

    @classmethod
    def refresh_session_tokens(
        cls,
        raw_refresh_token: str,
        session: Session,
    ) -> Dict[str, Any]:
        """
        Validates refresh token, enforces rotation by revoking the old token,
        and issues a fresh access token + new refresh token.
        """
        if not raw_refresh_token or not isinstance(raw_refresh_token, str):
            raise AuthServiceError("Invalid refresh token supplied", status_code=401)

        token_hash = hash_token(raw_refresh_token)
        token_record = UserRepository.get_refresh_token_by_hash(session, token_hash)

        if not token_record:
            raise AuthServiceError("Refresh token not found", status_code=401)

        if token_record.revoked_at is not None:
            raise AuthServiceError("Refresh token has been revoked", status_code=401)

        if token_record.expires_at <= utc_now():
            raise AuthServiceError("Refresh token has expired", status_code=401)

        user = UserRepository.get_user_by_id(session, token_record.user_id)
        if not user:
            raise AuthServiceError("Associated user account no longer exists", status_code=401)

        # Token Rotation: Revoke old token
        token_record.revoked_at = utc_now()
        session.flush()

        # Issue new token pair
        return cls.issue_token_pair(session, user)

    @classmethod
    def logout(cls, raw_refresh_token: str, session: Session) -> bool:
        """Revokes the presented refresh token."""
        if not raw_refresh_token:
            return False

        token_hash = hash_token(raw_refresh_token)
        return UserRepository.revoke_refresh_token(session, token_hash)
