"""Data Access Layer (Repository Pattern) for Users and Refresh Tokens."""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.db import RefreshTokenModel, UserModel, utc_now


class UserRepository:
    """Repository handling database access for User records and Refresh Tokens."""

    @staticmethod
    def get_user_by_id(session: Session, user_id: int) -> Optional[UserModel]:
        """Retrieves user by primary key ID."""
        stmt = select(UserModel).where(UserModel.id == user_id)
        return session.scalar(stmt)

    @staticmethod
    def get_user_by_github_id(session: Session, github_id: int) -> Optional[UserModel]:
        """Retrieves user by GitHub numeric ID."""
        stmt = select(UserModel).where(UserModel.github_id == github_id)
        return session.scalar(stmt)

    @staticmethod
    def upsert_github_user(
        session: Session,
        github_id: int,
        github_username: str,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
        is_admin: bool = False,
    ) -> UserModel:
        """
        Upserts user on GitHub login:
        Updates profile fields if exists, or inserts new record.
        """
        user = UserRepository.get_user_by_github_id(session, github_id)
        if user:
            user.github_username = github_username
            if email is not None:
                user.email = email
            if avatar_url is not None:
                user.avatar_url = avatar_url
            session.flush()
            return user

        user = UserModel(
            github_id=github_id,
            github_username=github_username,
            email=email,
            avatar_url=avatar_url,
            created_at=utc_now(),
            is_admin=is_admin,
        )
        session.add(user)
        session.flush()
        return user

    @staticmethod
    def create_refresh_token(
        session: Session,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshTokenModel:
        """Stores a new refresh token record with its SHA-256 hash."""
        token_record = RefreshTokenModel(
            user_id=user_id,
            token_hash=token_hash,
            created_at=utc_now(),
            expires_at=expires_at,
            revoked_at=None,
        )
        session.add(token_record)
        session.flush()
        return token_record

    @staticmethod
    def get_refresh_token_by_hash(
        session: Session,
        token_hash: str,
    ) -> Optional[RefreshTokenModel]:
        """Retrieves a refresh token record by token_hash."""
        stmt = select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        return session.scalar(stmt)

    @staticmethod
    def revoke_refresh_token(
        session: Session,
        token_hash: str,
    ) -> bool:
        """
        Marks a specific refresh token as revoked.
        Returns True if found and revoked, False if not found.
        """
        token_record = UserRepository.get_refresh_token_by_hash(session, token_hash)
        if token_record and token_record.revoked_at is None:
            token_record.revoked_at = utc_now()
            session.flush()
            return True
        return False

    @staticmethod
    def revoke_all_user_refresh_tokens(
        session: Session,
        user_id: int,
    ) -> int:
        """Revokes all active refresh tokens for a user (e.g., on password/session reset)."""
        now = utc_now()
        stmt = (
            select(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
        )
        tokens = session.scalars(stmt).all()
        for tok in tokens:
            tok.revoked_at = now
        session.flush()
        return len(tokens)
