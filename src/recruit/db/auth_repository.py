"""Database-backed authentication.

Separate from `Repository` on purpose: user and session management is a
different concern from hiring artifacts, and keeping them apart makes it
obvious which code paths touch credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select

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
from .repository import Repository


@dataclass(frozen=True)
class Account:
    """A user as an administrator needs to see them.

    `Principal` answers "who is this request" and deliberately carries nothing
    else. A team screen needs more — whether the account still works, when it
    was last used — and widening Principal to suit one page would put that
    extra state on every authorization check in the system.
    """

    user_id: int
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    @property
    def has_ever_signed_in(self) -> bool:
        return self.last_login_at is not None


class LocalAuth:
    """AuthAdapter backed by the users table.

    Real enough to run a small team on: hashed passwords, hashed session
    tokens, expiry, revocation, and deactivation.
    """

    requires_login = True

    def __init__(self, session_factory, session_hours: int = 12) -> None:
        self._session_factory = session_factory
        self._session_hours = session_hours

    # -- audit -------------------------------------------------------------
    @staticmethod
    def _record(db, event: str, actor: Principal | None, detail: dict) -> None:
        """Write a user-management action to the append-only log.

        Who was given access to candidate data, by whom, and when, is exactly
        the kind of question an audit asks — and until now account changes
        happened on a terminal and left no trace at all. Silent when no actor is
        supplied, because a first-run bootstrap has nobody to attribute it to.
        """
        if actor is None:
            return
        Repository(db).append_audit(
            event=event, actor=actor.email, actor_role=actor.role, detail=detail,
        )

    @staticmethod
    def _last_active_admin(db, user: User, *, becoming: str | None = None) -> bool:
        """Would changing this user leave the system with no working admin?

        The lockout this prevents is permanent. On a one-click deployment there
        is no terminal to recover from — an administrator who demotes or
        switches off their own only-admin account can never manage users again,
        and the fix would be redeploying from scratch.
        """
        if user.role != "admin" or becoming == "admin":
            return False
        others = db.scalar(
            select(func.count()).select_from(User).where(
                User.role == "admin", User.is_active.is_(True), User.id != user.id,
            )
        )
        return not others

    def _get(self, db, email: str) -> User:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None:
            raise AuthError(f"No user with email {email}")
        return user

    # -- user management ---------------------------------------------------
    def create_user(self, email: str, password: str, *, display_name: str,
                    role: str = "recruiter",
                    actor: Principal | None = None) -> Principal:
        email = email.strip().lower()
        with self._session_factory() as db:
            if db.scalar(select(User).where(User.email == email)):
                raise AuthError(f"A user with email {email} already exists.")
            user = User(
                email=email, display_name=display_name,
                password_hash=hash_password(password), role=role,
            )
            db.add(user)
            db.flush()
            self._record(db, "user.created", actor, {"account": email, "role": role})
            db.commit()
            db.refresh(user)
            return Principal(email=user.email, display_name=user.display_name,
                             role=user.role, user_id=user.id)

    def accounts(self) -> list[Account]:
        """Everyone, active or not, for the team screen."""
        with self._session_factory() as db:
            return [
                Account(
                    user_id=u.id, email=u.email, display_name=u.display_name,
                    role=u.role, is_active=u.is_active,
                    created_at=u.created_at, last_login_at=u.last_login_at,
                )
                for u in db.scalars(
                    select(User).order_by(User.is_active.desc(), User.email)
                )
            ]

    def reactivate(self, email: str, actor: Principal | None = None) -> None:
        """Switch an account back on.

        Deactivation has to be reversible from wherever it was done. Without
        this, one mis-click on a self-hosted instance with no terminal means
        that person is locked out for good.
        """
        with self._session_factory() as db:
            user = self._get(db, email)
            user.is_active = True
            self._record(db, "user.reactivated", actor, {"account": user.email})
            db.commit()

    def set_password(self, email: str, password: str, *,
                     revoke_sessions: bool = True,
                     actor: Principal | None = None) -> None:
        """Change a password.

        Revokes live sessions by default. A password change usually means the
        old one is suspect, and leaving sessions open would defeat the point.
        """
        with self._session_factory() as db:
            user = self._get(db, email)
            user.password_hash = hash_password(password)
            if revoke_sessions:
                now = datetime.now(UTC)
                for session in user.sessions:
                    if session.revoked_at is None:
                        session.revoked_at = now
            # The password itself is never recorded — only that it was changed,
            # by whom, and for whom.
            self._record(db, "user.password_reset", actor, {"account": user.email})
            db.commit()

    def set_role(self, email: str, role: str,
                 actor: Principal | None = None) -> None:
        with self._session_factory() as db:
            user = self._get(db, email)
            if self._last_active_admin(db, user, becoming=role):
                raise AuthError(
                    "This is the only administrator left. Give someone else the "
                    "administrator role first, or nobody will be able to manage "
                    "accounts afterwards."
                )
            was = user.role
            user.role = role
            self._record(db, "user.role_changed", actor,
                         {"account": user.email, "from": was, "to": role})
            db.commit()

    def deactivate(self, email: str, actor: Principal | None = None) -> None:
        """Deactivate and revoke every live session.

        Leaving sessions alive would mean a removed operator keeps working
        until their cookie expires.
        """
        with self._session_factory() as db:
            user = self._get(db, email)
            if self._last_active_admin(db, user):
                raise AuthError(
                    "This is the only administrator left. Switching it off would "
                    "lock everyone out of account management permanently — make "
                    "someone else an administrator first."
                )
            user.is_active = False
            now = datetime.now(UTC)
            for session in user.sessions:
                if session.revoked_at is None:
                    session.revoked_at = now
            self._record(db, "user.deactivated", actor, {"account": user.email})
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
    # Via `hosting`, not straight off the config: a hosted operator has a
    # dashboard of environment variables and no file they can edit.
    from ..hosting import auth_provider

    provider = auth_provider(config)

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
