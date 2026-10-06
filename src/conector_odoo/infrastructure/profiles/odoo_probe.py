"""Connection probe for Odoo profiles: shared URL/reachability/TLS steps, then Odoo auth."""

from collections.abc import Callable
from typing import Protocol

from conector_odoo.domain.errors import ConnectorError, OdooAuthError
from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundPolicy
from conector_odoo.domain.profiles import ConnectionProfile, ProbeStep, Secrets
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from conector_odoo.infrastructure.profiles.rest_probe import AUTH, check_endpoint, check_url


class OdooAuthenticator(Protocol):
    """The slice of ``OdooClient`` the probe needs (lets tests inject a fake)."""

    async def ensure_authenticated(self) -> int: ...

    async def aclose(self) -> None: ...


OdooClientFactory = Callable[[ConnectionProfile, Secrets], OdooAuthenticator]


def build_probe_client(
    profile: ConnectionProfile, secrets: Secrets, policy: OutboundPolicy = DEFAULT_POLICY
) -> OdooClient:
    """One-off JSON-RPC client for the profile; no retries so a bad test fails fast."""
    transport = JsonRpcTransport(
        profile.base_url.strip(),
        profile.odoo_db or "",
        profile.odoo_login or "",
        secrets.api_key or secrets.password or "",
        timeout=profile.timeout_seconds,
        max_retries=0,
        policy=policy,
    )
    return OdooClient(transport)


class OdooConnectionProbe:
    """``ConnectionProbe`` for ``ProfileType.ODOO`` (API key or password of ``odoo_login``)."""

    def __init__(
        self,
        client_factory: OdooClientFactory | None = None,
        policy: OutboundPolicy = DEFAULT_POLICY,
    ) -> None:
        self._policy = policy
        self._client_factory: OdooClientFactory = client_factory or (
            lambda profile, secrets: build_probe_client(profile, secrets, policy)
        )

    async def probe(self, profile: ConnectionProfile, secrets: Secrets) -> list[ProbeStep]:
        steps = [check_url(profile)]
        if not steps[-1].ok:
            return steps
        steps.extend(await check_endpoint(profile, self._policy))
        if not steps[-1].ok:
            return steps
        steps.append(await self._check_auth(profile, secrets))
        return steps

    async def _check_auth(self, profile: ConnectionProfile, secrets: Secrets) -> ProbeStep:
        if not profile.odoo_db or not profile.odoo_login:
            return ProbeStep(
                AUTH,
                False,
                "the Odoo database and login are required",
                "Fill in the database name and the login (user) of the Odoo account.",
            )
        if not (secrets.api_key or secrets.password):
            return ProbeStep(
                AUTH,
                False,
                "no credentials: an API key is required",
                "Provide the Odoo API key (or password) of the login.",
            )
        client = self._client_factory(profile, secrets)
        try:
            uid = await client.ensure_authenticated()
        except OdooAuthError:
            return ProbeStep(
                AUTH,
                False,
                "Odoo rejected the credentials",
                "Check the database name, the login and the API key (or password).",
            )
        except ConnectorError as exc:
            return ProbeStep(
                AUTH,
                False,
                f"Odoo could not be queried ({type(exc).__name__})",
                "The server answered but is not a working Odoo endpoint: check the URL and "
                "that /jsonrpc is enabled.",
            )
        finally:
            await client.aclose()
        return ProbeStep(AUTH, True, f"authenticated as uid {uid}")
