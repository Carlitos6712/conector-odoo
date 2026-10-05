"""Authentication strategies of the REST adapter, built from a ``ConnectionProfile`` + ``Secrets``.

Static credentials (API key, bearer) never refresh. OAuth2 client credentials and OIDC fetch an
access token, cache it until ``expires_in`` minus a safety skew and can be invalidated (the HTTP
client does that once on a 401). Nothing here logs or ``repr``s a secret.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from conector_odoo.domain.errors import RemoteAuthError, RemoteUnavailable
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, Secrets

TOKEN_SKEW_SECONDS = 30.0
DEFAULT_TOKEN_TTL_SECONDS = 300.0
_NO_M2M_HINT = (
    "the identity provider does not support the client_credentials grant, so it offers no "
    "machine-to-machine flow: use a static API key/bearer token or ask the provider for a "
    "service account"
)


class Authenticator(Protocol):
    can_refresh: bool

    async def headers(self, client: httpx.AsyncClient) -> dict[str, str]: ...

    async def invalidate(self) -> None: ...

    def secret_values(self) -> tuple[str, ...]:
        """Values that must be scrubbed from any text that may leave the process."""
        ...


class StaticAuth:
    can_refresh = False

    def __init__(self, header: str, value: str, secret: str) -> None:
        self._header = header
        self._value = value
        self._secret = secret

    async def headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        return {self._header: self._value}

    async def invalidate(self) -> None:
        return None

    def secret_values(self) -> tuple[str, ...]:
        return (self._secret,)

    def __repr__(self) -> str:
        return f"StaticAuth(header={self._header!r})"


class TokenAuth:
    can_refresh = True

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        scope: str | None,
        token_url: str | None,
        issuer_url: str | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._token_url = token_url
        self._issuer_url = issuer_url
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        async with self._lock:
            if self._token is None or self._clock() >= self._expires_at:
                await self._fetch(client)
        return {"Authorization": f"Bearer {self._token}"}

    async def invalidate(self) -> None:
        self._token = None

    def secret_values(self) -> tuple[str, ...]:
        values = [self._client_id, self._client_secret]
        if self._token:
            values.append(self._token)
        return tuple(values)

    def __repr__(self) -> str:
        return f"TokenAuth(token_url={self._token_url!r}, scope={self._scope!r})"

    async def _fetch(self, client: httpx.AsyncClient) -> None:
        url = self._token_url or await self._discover(client)
        form = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scope:
            form["scope"] = self._scope
        try:
            response = await client.post(url, data=form)
        except httpx.TransportError as exc:
            raise RemoteUnavailable(
                f"the token endpoint is unreachable ({type(exc).__name__})"
            ) from None
        body = _json_object(response)
        error = body.get("error")
        if response.status_code != 200:
            if error == "unsupported_grant_type":
                raise RemoteAuthError(f"token endpoint: {_NO_M2M_HINT}")
            code = error if isinstance(error, str) else "no error code"
            raise RemoteAuthError(
                f"the token endpoint refused the client credentials (HTTP {response.status_code}, "
                f"{code[:80]})"
            )
        token = body.get("access_token")
        if not isinstance(token, str) or not token:
            raise RemoteAuthError("the token endpoint answered without an access_token")
        ttl = body.get("expires_in")
        lifetime = float(ttl) if isinstance(ttl, int | float) else DEFAULT_TOKEN_TTL_SECONDS
        self._token = token
        self._expires_at = self._clock() + max(lifetime - TOKEN_SKEW_SECONDS, 0.0)

    async def _discover(self, client: httpx.AsyncClient) -> str:
        issuer = (self._issuer_url or "").rstrip("/")
        url = f"{issuer}/.well-known/openid-configuration"
        try:
            response = await client.get(url)
        except httpx.TransportError as exc:
            raise RemoteUnavailable(
                f"OIDC discovery failed ({type(exc).__name__}) at {issuer}"
            ) from None
        endpoint = _json_object(response).get("token_endpoint")
        if response.status_code != 200 or not isinstance(endpoint, str) or not endpoint:
            raise RemoteAuthError(
                f"cannot discover the OIDC token endpoint at {url} (HTTP {response.status_code}); "
                "set token_url on the profile"
            )
        self._token_url = endpoint
        return endpoint


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def build_authenticator(
    profile: ConnectionProfile,
    secrets: Secrets,
    *,
    clock: Callable[[], float] = time.monotonic,
    issuer_url: str | None = None,
) -> Authenticator:
    """Raises ``RemoteAuthError`` when the credentials the auth method needs are missing.

    OIDC resolves its token endpoint from ``profile.token_url``, else by discovery at
    ``issuer_url`` (default: the profile base URL).
    """
    method = profile.auth_method
    if method is AuthMethod.API_KEY:
        if not secrets.api_key:
            raise RemoteAuthError("an API key is required for this profile")
        return StaticAuth(profile.api_key_header, secrets.api_key, secrets.api_key)
    if method is AuthMethod.BEARER:
        if not secrets.token:
            raise RemoteAuthError("a bearer token is required for this profile")
        return StaticAuth("Authorization", f"Bearer {secrets.token}", secrets.token)
    if not (secrets.client_id and secrets.client_secret):
        raise RemoteAuthError("a client id and client secret are required for this profile")
    if method is AuthMethod.OAUTH2_CLIENT_CREDENTIALS and not profile.token_url:
        raise RemoteAuthError("token_url is required for oauth2_client_credentials")
    return TokenAuth(
        client_id=secrets.client_id,
        client_secret=secrets.client_secret,
        scope=profile.scope,
        token_url=profile.token_url,
        issuer_url=(issuer_url or profile.base_url) if method is AuthMethod.OIDC else None,
        clock=clock,
    )
