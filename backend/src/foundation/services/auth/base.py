import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import Depends

from src.foundation.core.config import settings
from src.foundation.core.exceptions import NotAuthenticatedException
from src.foundation.core.security import (
    Token,
    create_token,
    decode_token,
    hash_secret,
)
from src.foundation.models.user import User
from src.foundation.repositories.repository_manager import RepositoryManager
from src.foundation.services.base import BaseService

log = logging.getLogger(__name__)

# Applied when a soft-deleted user is restored: the returning person sets a new
# password and must not be locked out by an authenticator from the old account.
_MFA_RESET = frozendict(
    mfa_secret=None,
    mfa_enabled_at=None,
    mfa_recovery_codes=None,
    mfa_last_used_step=None,
    mfa_failed_attempts=0,
    mfa_locked_until=None,
)


class AuthBaseService(BaseService):
    """What the auth services share: issuing tokens and reading a session's
    refresh token."""

    def __init__(self, repos: Annotated[RepositoryManager, Depends()]) -> None:
        super().__init__(repos)

    async def _issue_tokens(self, user: User, organization_id: int) -> Token:
        """Create an access token plus a new refresh-token session row.

        Each call starts a new session (one row per device/browser); existing
        sessions are untouched. Rotation/revocation is handled by the callers
        via revoke_by_jti / delete_by_user.
        """
        access_token = create_token(
            user,
            settings.auth_access_token_expiry,
            organization_id=organization_id,
        )
        jti = str(uuid4())
        refresh_token = create_token(
            user,
            settings.auth_refresh_token_expiry,
            include_user_claims=False,
            jti=jti,
            token_type="refresh",  # noqa: S106 - JWT kind, not a secret
        )
        expires_at = datetime.now(UTC) + timedelta(
            seconds=settings.auth_refresh_token_expiry,
        )
        await self.repos.refresh_token.create(
            user,
            hash_secret(refresh_token),
            expires_at,
            jti=jti,
        )
        return Token(access_token=access_token, refresh_token=refresh_token)

    def _decode_session_jti(
        self,
        refresh_token: str | None,
        user_id: int | None = None,
    ) -> str | None:
        """Best-effort extraction of the session jti from a refresh token.
        Returns None for missing/invalid/expired tokens or a user mismatch."""
        if not refresh_token:
            return None
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except NotAuthenticatedException:
            return None
        if user_id is not None and int(payload.get("sub", 0)) != user_id:
            return None
        return payload.get("jti")
