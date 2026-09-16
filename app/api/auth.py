"""Authentication API Router for GitHub OAuth, Session Tokens, and Logout."""

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.db import UserModel
from app.security.auth import refresh_rate_limiter
from app.services.auth_service import AuthService, AuthServiceError

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(..., description="Opaque refresh token previously issued")


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., description="Opaque refresh token to revoke")


class UserProfileResponse(BaseModel):
    id: int
    github_id: int
    github_username: str
    email: Optional[str]
    avatar_url: Optional[str]
    is_admin: bool
    created_at: str


@router.get("/github/login", summary="Initiate GitHub OAuth Login")
def github_login(
    redirect_url: Optional[str] = Query(
        None, description="Optional post-authentication redirect destination URL"
    ),
):
    """
    Redirects user to GitHub OAuth authorize screen with a cryptographically
    random, single-use state token for CSRF protection.
    """
    try:
        auth_url = AuthService.get_login_redirect_url(redirect_target=redirect_url)
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    return RedirectResponse(url=auth_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/github/callback", summary="Handle GitHub OAuth Callback")
async def github_callback(
    request: Request,
    code: Optional[str] = Query(None, description="GitHub authorization code"),
    state: Optional[str] = Query(None, description="OAuth state parameter for CSRF validation"),
    error: Optional[str] = Query(None, description="OAuth error code from GitHub"),
    error_description: Optional[str] = Query(None, description="OAuth error description from GitHub"),
    session: Session = Depends(get_db),
):
    """
    Validates state parameter, exchanges code for access token, fetches profile,
    upserts User record, and issues access + refresh token pair.
    Sets secure httpOnly session cookies for browser clients.
    """
    if error:
        detail_msg = error_description or error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"GitHub OAuth error: {detail_msg}",
        )

    if not state or not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required OAuth parameters ('code' and 'state')",
        )

    try:
        tokens, redirect_target = await AuthService.process_oauth_callback(
            code=code, state=state, session=session
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process authentication callback: {exc}",
        )

    # Check if request prefers HTML redirect (browser navigation)
    accept_header = request.headers.get("accept", "")
    is_html_browser = "text/html" in accept_header and "application/json" not in accept_header

    if is_html_browser:
        target = redirect_target if redirect_target else "/dashboard"
        response = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
    else:
        response = JSONResponse(content=tokens, status_code=status.HTTP_200_OK)

    # Set httpOnly cookies for seamless browser session management
    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        httponly=True,
        samesite="lax",
        secure=False,  # Can be true in prod HTTPS
        max_age=900,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=30 * 86400,
        path="/",
    )

    return response


@router.post("/refresh", summary="Rotate and Refresh Access Token")
def refresh_session_token(
    request: Request,
    payload: RefreshTokenRequest,
    session: Session = Depends(get_db),
):
    """
    Validates refresh token, enforces rotation by revoking the old token,
    and returns a fresh access token + new refresh token.
    Throttled per client IP to prevent brute-force attacks.
    """
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"refresh:{client_ip}"

    if not refresh_rate_limiter.is_allowed(rate_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many refresh requests. Please slow down.",
        )

    try:
        new_tokens = AuthService.refresh_session_tokens(
            raw_refresh_token=payload.refresh_token,
            session=session,
        )
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {exc}",
        )

    response = JSONResponse(content=new_tokens, status_code=status.HTTP_200_OK)
    response.set_cookie(
        key="access_token",
        value=new_tokens["access_token"],
        httponly=True,
        samesite="lax",
        max_age=900,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=new_tokens["refresh_token"],
        httponly=True,
        samesite="lax",
        max_age=30 * 86400,
        path="/",
    )
    return response


@router.post("/logout", summary="Revoke Session Refresh Token")
def logout(
    payload: LogoutRequest,
    session: Session = Depends(get_db),
):
    """
    Revokes the provided refresh token immediately.
    """
    success = AuthService.logout(raw_refresh_token=payload.refresh_token, session=session)
    response = JSONResponse(
        content={
            "status": "success",
            "message": "Session refresh token revoked successfully" if success else "Token already revoked or non-existent",
        },
        status_code=status.HTTP_200_OK,
    )
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response


@router.get("/logout", summary="Browser Logout and Cookie Clear")
def browser_logout():
    """Clears authentication cookies and redirects user to login view."""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return response


@router.get("/me", response_model=UserProfileResponse, summary="Get Current Authenticated User Profile")
def get_authenticated_user_profile(
    current_user: UserModel = Depends(get_current_user),
):
    """
    Returns profile information for the authenticated user based on verified JWT claims.
    """
    return UserProfileResponse(
        id=current_user.id,
        github_id=current_user.github_id,
        github_username=current_user.github_username,
        email=current_user.email,
        avatar_url=current_user.avatar_url,
        is_admin=current_user.is_admin,
        created_at=current_user.created_at.isoformat(),
    )
