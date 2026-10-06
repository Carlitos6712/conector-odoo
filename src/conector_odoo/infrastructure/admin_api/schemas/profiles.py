from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, SecretStr

from conector_odoo.application.profiles import ProfileView
from conector_odoo.domain.profiles import (
    AuthMethod,
    ConnectionProfile,
    ConnectionTestResult,
    ProfileType,
    Secrets,
)
from conector_odoo.infrastructure.admin_api.schemas.common import StrictModel


class SecretsIn(StrictModel):
    """Write-only credentials. Omitted/``null`` keeps the stored value, ``""`` clears it."""

    api_key: SecretStr | None = None
    token: SecretStr | None = None
    client_id: SecretStr | None = None
    client_secret: SecretStr | None = None
    password: SecretStr | None = None

    def to_domain(self) -> Secrets:
        def plain(value: SecretStr | None) -> str | None:
            return None if value is None else value.get_secret_value()

        return Secrets(
            api_key=plain(self.api_key),
            token=plain(self.token),
            client_id=plain(self.client_id),
            client_secret=plain(self.client_secret),
            password=plain(self.password),
        )


class ProfileIn(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    type: ProfileType
    base_url: str = Field(min_length=1, max_length=2048)
    auth_method: AuthMethod
    extra_headers: dict[str, str] = Field(default_factory=dict)
    tls_verify: bool = True
    timeout_seconds: float = 30.0
    odoo_db: str | None = None
    odoo_login: str | None = None
    token_url: str | None = None
    username: str | None = Field(default=None, max_length=256)
    scope: str | None = None
    api_key_header: str = "X-API-Key"
    secrets: SecretsIn | None = None

    def to_domain(self, profile_id: int | None = None) -> ConnectionProfile:
        return ConnectionProfile(
            id=profile_id,
            name=self.name,
            type=self.type,
            base_url=self.base_url,
            auth_method=self.auth_method,
            extra_headers=dict(self.extra_headers),
            tls_verify=self.tls_verify,
            timeout_seconds=self.timeout_seconds,
            odoo_db=self.odoo_db,
            odoo_login=self.odoo_login,
            token_url=self.token_url,
            username=self.username,
            scope=self.scope,
            api_key_header=self.api_key_header,
        )

    def secrets_domain(self) -> Secrets | None:
        return None if self.secrets is None else self.secrets.to_domain()


class ProfileOut(BaseModel):
    """A profile as shown to the admin: ``has_secret`` flags instead of any credential."""

    id: int
    name: str
    type: ProfileType
    base_url: str
    auth_method: AuthMethod
    extra_headers: dict[str, str]
    tls_verify: bool
    timeout_seconds: float
    odoo_db: str | None
    odoo_login: str | None
    token_url: str | None
    username: str | None
    scope: str | None
    api_key_header: str
    has_secret: dict[str, bool]
    created_at: datetime | None
    updated_at: datetime | None
    is_active: bool
    last_connected_at: datetime | None

    @classmethod
    def of(cls, view: ProfileView) -> Self:
        return cls(
            id=view.id,
            name=view.name,
            type=view.type,
            base_url=view.base_url,
            auth_method=view.auth_method,
            extra_headers=view.extra_headers,
            tls_verify=view.tls_verify,
            timeout_seconds=view.timeout_seconds,
            odoo_db=view.odoo_db,
            odoo_login=view.odoo_login,
            token_url=view.token_url,
            username=view.username,
            scope=view.scope,
            api_key_header=view.api_key_header,
            has_secret=view.has_secret,
            created_at=view.created_at,
            updated_at=view.updated_at,
            is_active=view.is_active,
            last_connected_at=view.last_connected_at,
        )


class ProfileListOut(BaseModel):
    items: list[ProfileOut]


class ProbeStepOut(BaseModel):
    name: str
    ok: bool
    detail: str
    hint: str | None


class ConnectionTestOut(BaseModel):
    ok: bool
    failed_step: str | None
    steps: list[ProbeStepOut]

    @classmethod
    def of(cls, result: ConnectionTestResult) -> Self:
        return cls(
            ok=result.ok,
            failed_step=result.failed_step,
            steps=[
                ProbeStepOut(name=s.name, ok=s.ok, detail=s.detail, hint=s.hint)
                for s in result.steps
            ],
        )
