"""HTTP connection probe for REST profiles (also provides the shared reachability/TLS steps).

The run is ordered ``url_valid`` -> ``reachable`` -> ``tls`` -> ``auth`` and stops at the first
failure. Failures are classified (DNS, refused, timeout, TLS handshake, 401/403) into steps with an
actionable hint. Step details never contain credentials.
"""

import socket
import ssl
from urllib.parse import urlsplit

import httpx

from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProbeStep, Secrets

URL_VALID = "url_valid"
REACHABLE = "reachable"
TLS = "tls"
AUTH = "auth"


# httpx keeps the original OS/OpenSSL text in the message (the cause chain is not always kept).
_TLS_MARKERS = ("CERTIFICATE_VERIFY_FAILED", "certificate verify failed", "[SSL:")
_DNS_MARKERS = (
    "Name or service not known",
    "nodename nor servname",
    "Temporary failure in name resolution",
    "getaddrinfo failed",
    "No address associated",
)


def check_url(profile: ConnectionProfile) -> ProbeStep:
    parts = urlsplit(profile.base_url.strip())
    if parts.scheme in ("http", "https") and parts.hostname:
        return ProbeStep(URL_VALID, True, f"{parts.scheme}://{parts.hostname}")
    return ProbeStep(
        URL_VALID,
        False,
        "the base URL is not a valid http(s) URL",
        "Use a full URL such as https://api.example.com (scheme and host are required).",
    )


async def check_endpoint(profile: ConnectionProfile) -> list[ProbeStep]:
    """``reachable`` and ``tls`` steps: one unauthenticated GET on the base URL (any HTTP answer,
    even 401/404, proves the host is up and the TLS handshake worked)."""
    try:
        async with httpx.AsyncClient(
            verify=profile.tls_verify, timeout=profile.timeout_seconds, follow_redirects=False
        ) as client:
            await client.get(profile.base_url.strip(), headers=profile.extra_headers)
    except httpx.TransportError as exc:
        return _classify(exc, profile)
    if profile.base_url.strip().lower().startswith("https"):
        detail = (
            "certificate verification disabled (tls_verify=false)"
            if not profile.tls_verify
            else "TLS handshake and certificate verified"
        )
    else:
        detail = "plain http, TLS not used"
    return [
        ProbeStep(REACHABLE, True, "the server answered"),
        ProbeStep(TLS, True, detail),
    ]


def _classify(exc: httpx.TransportError, profile: ConnectionProfile) -> list[ProbeStep]:
    chain = _causes(exc)
    reached = ProbeStep(REACHABLE, True, "the server answered the TCP connection")
    message = str(exc)
    if any(isinstance(c, ssl.SSLError) for c in chain) or any(
        marker in message for marker in _TLS_MARKERS
    ):
        return [
            reached,
            ProbeStep(
                TLS,
                False,
                "TLS handshake or certificate verification failed",
                "Check the server certificate (expired, self-signed or hostname mismatch). For a "
                "private CA or a test server you can set tls_verify=false (not for production).",
            ),
        ]
    if isinstance(exc, httpx.TimeoutException):
        return [
            ProbeStep(
                REACHABLE,
                False,
                f"the request timed out after {profile.timeout_seconds:g}s",
                "The host did not answer in time: check firewall/VPN or raise the timeout.",
            )
        ]
    if any(isinstance(c, socket.gaierror) for c in chain) or any(
        marker in message for marker in _DNS_MARKERS
    ):
        return [
            ProbeStep(
                REACHABLE,
                False,
                "DNS lookup failed: the host name cannot be resolved",
                "Check the host name for typos and that this machine can resolve it.",
            )
        ]
    return [
        ProbeStep(
            REACHABLE,
            False,
            "could not connect (connection refused or network unreachable)",
            "Check the host and port, that the service is running and that no firewall blocks it.",
        )
    ]


def _causes(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


class RestConnectionProbe:
    """``ConnectionProbe`` for ``ProfileType.REST``."""

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]:
        steps = [check_url(profile)]
        if not steps[-1].ok:
            return steps
        steps.extend(await check_endpoint(profile))
        if not steps[-1].ok:
            return steps
        steps.append(await self._check_auth(profile, secrets))
        return steps

    async def _check_auth(self, profile: ConnectionProfile, secrets: Secrets) -> ProbeStep:
        try:
            async with httpx.AsyncClient(
                verify=profile.tls_verify, timeout=profile.timeout_seconds
            ) as client:
                headers = dict(profile.extra_headers)
                failure = await _add_credentials(client, profile, secrets, headers)
                if failure:
                    return failure
                response = await client.get(profile.base_url.strip(), headers=headers)
        except httpx.TransportError as exc:
            return ProbeStep(
                AUTH,
                False,
                f"the authenticated request failed ({type(exc).__name__})",
                "The server stopped answering during the credential check; retry the test.",
            )
        return _judge(response.status_code)


def _judge(status: int) -> ProbeStep:
    if status in (401, 403):
        return ProbeStep(
            AUTH,
            False,
            f"the server rejected the credentials (HTTP {status})",
            "Check the key/token/client credentials and that the account has access to the API.",
        )
    if status >= 500:
        return ProbeStep(
            AUTH,
            False,
            f"the server failed while checking credentials (HTTP {status})",
            "The API is reachable but erroring; try again later or check the server logs.",
        )
    return ProbeStep(AUTH, True, f"credentials accepted (HTTP {status})")


async def _add_credentials(
    client: httpx.AsyncClient,
    profile: ConnectionProfile,
    secrets: Secrets,
    headers: dict[str, str],
) -> ProbeStep | None:
    """Add the auth header; return a failed step when credentials are missing or unobtainable."""
    method = profile.auth_method
    if method is AuthMethod.API_KEY:
        if not secrets.api_key:
            return _missing("an API key")
        headers[profile.api_key_header] = secrets.api_key
    elif method is AuthMethod.BEARER:
        if not secrets.token:
            return _missing("a bearer token")
        headers["Authorization"] = f"Bearer {secrets.token}"
    else:
        if not (secrets.client_id and secrets.client_secret):
            return _missing("a client id and client secret")
        if not profile.token_url:
            return ProbeStep(
                AUTH,
                False,
                "token_url is not set",
                f"{method.value} needs the token endpoint URL to request an access token.",
            )
        token = await _fetch_token(client, profile, secrets)
        if isinstance(token, ProbeStep):
            return token
        headers["Authorization"] = f"Bearer {token}"
    return None


def _missing(what: str) -> ProbeStep:
    return ProbeStep(
        AUTH, False, f"no credentials: {what} is required", f"Provide {what} for this profile."
    )


async def _fetch_token(
    client: httpx.AsyncClient, profile: ConnectionProfile, secrets: Secrets
) -> str | ProbeStep:
    form = {
        "grant_type": "client_credentials",
        "client_id": secrets.client_id or "",
        "client_secret": secrets.client_secret or "",
    }
    if profile.scope:
        form["scope"] = profile.scope
    try:
        response = await client.post(profile.token_url or "", data=form)
    except httpx.TransportError as exc:
        return ProbeStep(
            AUTH,
            False,
            f"the token endpoint is unreachable ({type(exc).__name__})",
            "Check token_url, and that the identity provider is reachable from here.",
        )
    token = _access_token(response)
    if token is None:
        return ProbeStep(
            AUTH,
            False,
            f"the token endpoint refused the client credentials (HTTP {response.status_code})",
            "Check client id/secret, the granted scope and that client_credentials is enabled.",
        )
    return token


def _access_token(response: httpx.Response) -> str | None:
    if response.status_code != 200:
        return None
    try:
        value = response.json().get("access_token")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) and value else None
