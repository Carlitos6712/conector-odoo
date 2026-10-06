"""Connection profiles: how to reach an external system (Odoo or a REST API).

Pure domain: no framework, crypto or HTTP imports. Secrets live in the separate ``Secrets``
value object so a profile can be logged, serialised and shown without ever carrying a credential;
the profile only remembers the *names* of the secrets that are stored (``secret_fields``).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from conector_odoo.domain.errors import ProfileValidationError


class ProfileType(StrEnum):
    ODOO = "odoo"
    REST = "rest"


class AuthMethod(StrEnum):
    API_KEY = "api_key"
    BEARER = "bearer"
    OAUTH2_CLIENT_CREDENTIALS = "oauth2_client_credentials"
    OIDC = "oidc"


SECRET_FIELDS = ("api_key", "token", "client_id", "client_secret", "password")


@dataclass(frozen=True, slots=True, repr=False)
class Secrets:
    """Credentials of a profile. ``None`` means "not provided" (kept on update), ``""`` clears.

    ``repr``/``str`` list only the names of the fields that are set, never their values. Do not
    serialise it with ``dataclasses.asdict`` outside the vault.
    """

    api_key: str | None = None
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    password: str | None = None

    def present_fields(self) -> frozenset[str]:
        return frozenset(name for name in SECRET_FIELDS if getattr(self, name))

    def merged(self, update: "Secrets") -> "Secrets":
        """Apply ``update``: ``None`` keeps the current value, ``""`` clears it."""
        values: dict[str, str | None] = {}
        for name in SECRET_FIELDS:
            new = getattr(update, name)
            values[name] = getattr(self, name) if new is None else (new or None)
        return Secrets(**values)

    def as_dict(self) -> dict[str, str]:
        """Set fields only; meant for the vault, never for logs or API output."""
        return {name: value for name in SECRET_FIELDS if (value := getattr(self, name))}

    def __repr__(self) -> str:
        return f"Secrets(set={sorted(self.present_fields())})"


@dataclass(frozen=True, slots=True)
class ConnectionProfile:
    """Non-secret description of a connection.

    ``extra_headers`` are sent as-is and shown in the admin, so they must not carry credentials
    (use ``Secrets``). Odoo profiles use ``odoo_db``/``odoo_login``; OAuth2/OIDC profiles use
    ``token_url`` and ``scope``; API-key profiles send the key in ``api_key_header``.
    """

    id: int | None
    name: str
    type: ProfileType
    base_url: str
    auth_method: AuthMethod
    extra_headers: dict[str, str] = field(default_factory=dict)
    tls_verify: bool = True
    timeout_seconds: float = 30.0
    odoo_db: str | None = None
    odoo_login: str | None = None
    token_url: str | None = None
    scope: str | None = None
    api_key_header: str = "X-API-Key"
    secret_fields: frozenset[str] = frozenset()
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ProfileValidationError("profile name must not be empty")
        if self.timeout_seconds <= 0:
            raise ProfileValidationError("timeout_seconds must be greater than 0")
        if unknown := self.secret_fields - set(SECRET_FIELDS):
            raise ProfileValidationError(f"unknown secret fields {sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class StoredProfile:
    """A profile as persisted: the clear description plus its opaque encrypted secrets."""

    profile: ConnectionProfile
    secrets_blob: bytes | None


@dataclass(frozen=True, slots=True)
class ProbeStep:
    """One check of a connection test. ``hint`` says how to fix a failed step."""

    name: str
    ok: bool
    detail: str
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    ok: bool
    failed_step: str | None
    steps: tuple[ProbeStep, ...]

    @classmethod
    def from_steps(cls, steps: Sequence[ProbeStep]) -> "ConnectionTestResult":
        """Keep the steps up to and including the first failure (later ones never ran)."""
        kept: list[ProbeStep] = []
        for step in steps:
            kept.append(step)
            if not step.ok:
                return cls(ok=False, failed_step=step.name, steps=tuple(kept))
        return cls(ok=True, failed_step=None, steps=tuple(kept))
