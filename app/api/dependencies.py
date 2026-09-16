"""FastAPI Authentication & Security Dependencies (Prompt 1 & 3)."""

from typing import Generator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.db import UserModel
from app.security.auth import AuthVerificationError, decode_and_verify_access_token
from app.storage.user_repository import UserRepository

# Reusable security scheme (auto_error=False to allow custom 401 response handling)
bearer_scheme = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    """Provides a transactional database session per request."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def extract_token_from_request(
    request: Request,
    auth_creds: Optional[HTTPAuthorizationCredentials] = None,
) -> Optional[str]:
    """Extract token either from Bearer Authorization header or httpOnly cookie."""
    if auth_creds and auth_creds.credentials:
        return auth_creds.credentials
    # Fallback to cookie
    return request.cookies.get("access_token")


def get_current_user(
    request: Request,
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> UserModel:
    """
    FastAPI dependency that validates the JWT access token and returns the authenticated User.
    Supports both Authorization: Bearer <token> headers and httpOnly access_token cookies.
    """
    token = extract_token_from_request(request, auth_creds)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header. Expected 'Bearer <token>' or session cookie.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_and_verify_access_token(token)
    except AuthVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing valid user identifier claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = UserRepository.get_user_by_id(session, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with this token no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_current_user_optional(
    request: Request,
    auth_creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    session: Session = Depends(get_db),
) -> Optional[UserModel]:
    """Optional user dependency that returns None rather than raising 401 if unauthenticated."""
    token = extract_token_from_request(request, auth_creds)
    if not token:
        return None

    try:
        payload = decode_and_verify_access_token(token)
        user_id = payload.get("user_id")
        if not user_id:
            return None
        return UserRepository.get_user_by_id(session, user_id)
    except Exception:
        return None


def get_current_admin_user(
    current_user: UserModel = Depends(get_current_user),
) -> UserModel:
    """Dependency verifying that the authenticated user possesses admin privileges."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required for this operation",
        )
    return current_user
