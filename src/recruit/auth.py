"""Authentication and role-based access control.

Password hashing uses `hashlib.scrypt` from the standard library. bcrypt and
argon2 are fine choices but both are compiled dependencies, and hard rule 9 says
the pipeline must install with no compiler. scrypt is memory-hard, in the
stdlib, and adequate here.

**Roles are enforced at the route, not in the template.** Hiding a button is a
UI courtesy; anyone can still type the URL. Every protected route declares the
permission it needs and the dependency refuses the request without it.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# scrypt parameters. n=2**14 keeps a single hash around 100ms on a laptop —
# slow enough to make offline guessing expensive, fast enough for a login form.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16
KEY_BYTES = 32

SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_HOURS = 12


# -- roles --------------------------------------------------------------------
#
# Derived from the RACI tables in Workflow_Spec.md §10. Deliberately small:
# every role added is a role somebody has to reason about during an audit.

PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "review", "approve", "reject", "escalate",
        "override", "configure", "read_audit", "manage_users",
    },
    "hiring_manager": {"review", "approve", "reject", "escalate"},
    # A recruiter prepares and escalates but does not make the call. That is the
    # human-in-the-loop boundary from Workflow_Spec.md §15, expressed in code.
    "recruiter": {"review", "escalate"},
    "auditor": {"read_audit"},
}

ROLES = tuple(PERMISSIONS)


class AuthError(RuntimeError):
    """Authentication or authorization failure."""


class PermissionDenied(AuthError):
    def __init__(self, role: str, permission: str) -> None:
        super().__init__(
            f"Role '{role}' does not have permission '{permission}'."
        )
        self.role = role
        self.permission = permission


# -- passwords ----------------------------------------------------------------
def hash_password(password: str) -> str:
    """Return `scrypt$n$r$p$salt$key`, all hex. Salt is per-password."""
    if not password or len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N,
                         r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time verification. Returns False rather than raising on a
    malformed hash — a corrupt row must not become an authentication bypass or
    a 500."""
    try:
        scheme, n, r, p, salt_hex, key_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(key_hex)),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(candidate, bytes.fromhex(key_hex))


# -- sessions -----------------------------------------------------------------
def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Sessions are stored hashed.

    A stolen database dump then yields no usable session cookies. SHA-256 is
    right here rather than scrypt: the token already has 256 bits of entropy,
    so there is nothing to brute-force and no reason to pay the cost on every
    request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(hours: int = DEFAULT_SESSION_HOURS) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)


# -- principal ----------------------------------------------------------------
@dataclass(frozen=True)
class Principal:
    """Who is acting. Recorded on every audited decision."""

    email: str
    display_name: str
    role: str
    user_id: int | None = None

    def __post_init__(self) -> None:
        if self.role not in PERMISSIONS:
            raise AuthError(f"Unknown role: {self.role!r}. Valid: {', '.join(ROLES)}")

    @property
    def permissions(self) -> set[str]:
        return PERMISSIONS[self.role]

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise PermissionDenied(self.role, permission)


# -- adapters -----------------------------------------------------------------
class SingleUserAuth:
    """One hardcoded operator, for local development.

    Kept because `pip install -e .` must produce something runnable without a
    user database. Never appropriate beyond a laptop: it authenticates nobody
    and every audit entry names the same person.
    """

    def __init__(self, email: str = "operator@localhost",
                 display_name: str = "Local Operator",
                 role: str = "admin") -> None:
        self._principal = Principal(email=email, display_name=display_name, role=role)

    def authenticate(self, credentials: dict[str, str]) -> Principal | None:
        return self._principal

    def principal_for_token(self, token: str) -> Principal | None:
        return self._principal

    def login(self, email: str, password: str) -> tuple[Principal, str] | None:
        return self._principal, "single-user"

    def logout(self, token: str) -> None:
        return None

    @property
    def requires_login(self) -> bool:
        return False


class OIDCAuth:
    """Placeholder for enterprise SSO.

    Deliberately raises rather than silently falling back to something weaker:
    an organization that configures `oidc` and quietly gets single-user auth has
    a security incident, not a configuration warning.
    """

    def __init__(self, **_: object) -> None:
        raise NotImplementedError(
            "OIDC single sign-on is not implemented yet.\n"
            "  Available now: adapters.auth.provider = 'local' (username/password)\n"
            "  or 'single_user' for development.\n"
            "  Tracked in CLAUDE.md under Deferred work."
        )
