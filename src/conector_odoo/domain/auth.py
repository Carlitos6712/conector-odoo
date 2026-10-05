"""Admin users and roles (pure domain, stdlib only).

``admin`` may do everything; ``operator`` is read-only: it may call safe (GET) endpoints and
nothing that mutates data or triggers a run.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from conector_odoo.domain.errors import AdminUserInvalid

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256  # bounds the hashing cost an attacker can request
MAX_USERNAME_LENGTH = 64


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"


@dataclass(frozen=True, slots=True)
class AdminUser:
    id: int
    username: str
    role: Role
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AdminSession:
    """A server-side session. Only the digest of the cookie token is ever stored."""

    token_hash: str
    user_id: int
    csrf_token: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime


def normalize_username(username: str) -> str:
    cleaned = username.strip()
    if not cleaned or len(cleaned) > MAX_USERNAME_LENGTH:
        raise AdminUserInvalid(f"username must have 1 to {MAX_USERNAME_LENGTH} characters")
    return cleaned


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AdminUserInvalid(f"password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AdminUserInvalid(f"password must be at most {MAX_PASSWORD_LENGTH} characters long")
