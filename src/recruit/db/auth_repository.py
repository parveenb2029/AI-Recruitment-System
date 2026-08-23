"""Database-backed authentication.

Separate from `Repository` on purpose: user and session management is a
different concern from hiring artifacts, and keeping them apart makes it
obvious which code paths touch credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from ..auth import (
    AuthError,
    Principal,
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    verify_password,
)
from .models import Session, User


class LocalAuth:
    """AuthAdapter backed by the users table.

    Real enough to run a small team on: hashed passwords, hashed session
    tokens, expiry, revocation, and deactivation.
    """

    requires_login = True

    def __init__(self, session_factory, session_hours: int = 12) -> None:
        self._session_factory = session_factory
        self._session_hours = session_hours

    # -- user management ---------------------------------------------------
    def create_user(self, email: str, password: str, *, display_name: str,
                    role: str = "recruiter") -> Principal:
        email = email.strip().lower()
        with self._session_factory() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise AuthError(f"A user with email {email} already exists.")
            user = User(
                email=email, display_name=display_name,
                password_hash=hash_password(password), role=role,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return Principal(email=user.email, display_name=user.display_name,
                             role=user.role, user_id=user.id)

    def set_password(self, email: str, password: str, *,
                     revoke_sessions: bool = True) -> None:
        """Change a password.

        Revokes live sessions by default. A password change usually means the
        old one is suspect, and leaving sessions open would defeat the point.
        """
        with self._session_factory() as db:
            user = db.scalar(select(User).where(User.email == email.strip().lower()))
            if user is None:
                raise AuthError(f"No user with email {email}")
            user.password_hash = hash_password(password)
            if revoke_sessions:
                now = datetime.now(UTC)
                for session in user.sessions:
                    if session.revoked_at is None:
                        session.revoked_at = now
            db.commit()

    def set_role(self, email: str, role: str) -> None:
        with self._session_factory() as db:
            user = db.scalar(select(User).where(User.email == email.strip().lower()))
            if user is None:
                raise AuthError(f"No user with email {email}")
            user.role = role
            db.commit()

    def deactivate(self, email: str) -> None:
        """Deactivate and revoke every live session.

        Leaving sessions alive would mean a removed operator keeps working
        until their cookie expires.
        """
        with self._session_factory() as db:
            user = db.scalar(select(User).where(User.email == email.strip().lower()))
            if user is None:
                raise AuthError(f"No user with email {email}")
            user.is_active = False
            now = datetime.now(UTC)
            for session in user.sessions:
                if session.revoked_at is None:
                    session.revoked_at = now
            db.commit()

    def list_users(self) -> list[Principal]:
        with self._session_factory() as db:
            return [
                Principal(email=u.email, display_name=u.display_name,
                          role=u.role, user_id=u.id)
                for u in db.scalars(select(User).order_by(User.email))
            ]

    # -- login -------------------------------------------------------------
    def login(self, email: str, password: str) -> tuple[Principal, str] | None:
        """Returns (principal, session_token) or None.

        Returns None for every failure mode — unknown user, wrong password,
        deactivated account — so the response cannot be used to enumerate who
        has an account.
        """
        email = (email or "").strip().lower()
        with self._session_factory() as db:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                # Hash anyway. Returning early on an unknown user makes the
                # response measurably faster and leaks which emails exist.
                verify_password(password or "", hash_password("not-a-real-password"))
                return None
            if not verify_password(password or "", user.password_hash):
                return None
            if not user.is_active:
                return None

            token = new_session_token()
            db.add(Session(
                token_hash=hash_token(token), user_id=user.id,
                expires_at=session_expiry(self._session_hours),
            ))
            user.last_login_at = datetime.now(UTC)
            db.commit()
            principal = Principal(email=user.email, display_name=user.display_name,
                                  role=user.role, user_id=user.id)
        return principal, token

    def principal_for_token(self, token: str) -> Principal | None:
        if not token:
            return None
        with self._session_factory() as db:
            session = db.scalar(
                select(Session).where(Session.token_hash == hash_token(token))
            )
            if session is None or session.revoked_at is not None:
                return None
            expires = session.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires <= datetime.now(UTC):
                return None
            user = session.user
            if user is None or not user.is_active:
                return None
            return Principal(email=user.email, display_name=user.display_name,
                             role=user.role, user_id=user.id)

    def logout(self, token: str) -> None:
        if not token:
            return
        with self._session_factory() as db:
            session = db.scalar(
                select(Session).where(Session.token_hash == hash_token(token))
            )
            if session is not None and session.revoked_at is None:
                session.revoked_at = datetime.now(UTC)
                db.commit()

    def purge_expired_sessions(self) -> int:
        with self._session_factory() as db:
            expired = list(db.scalars(
                select(Session).where(Session.expires_at <= datetime.now(UTC))
            ))
            for session in expired:
                db.delete(session)
            db.commit()
            return len(expired)


def build_auth(config, session_factory):
    """Construct the configured auth adapter."""
    provider = config.get("adapters.auth.provider", "single_user") if config else "single_user"

    if provider == "local":
        hours = int(config.get("adapters.auth.local.session_hours", 12)) if config else 12
        return LocalAuth(session_factory, session_hours=hours)

    if provider == "single_user":
        from ..auth import SingleUserAuth
        if config is None:
            return SingleUserAuth()
        return SingleUserAuth(
            email=config.get("adapters.auth.single_user.email", "operator@localhost"),
            display_name=config.get("adapters.auth.single_user.display_name",
                                    "Local Operator"),
            role=config.get("adapters.auth.single_user.role", "admin"),
        )

    if provider == "oidc":
        from ..auth import OIDCAuth
        return OIDCAuth()

    raise NotImplementedError(
        f"Auth provider '{provider}' is not implemented. "
        f"Available: local, single_user."
    )
