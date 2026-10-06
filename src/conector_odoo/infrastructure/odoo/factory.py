"""Build the Odoo transport and client selected by ``Settings.odoo_protocol``."""

from typing import Literal

from conector_odoo.application.pagination import DEFAULT_MAX_CONCURRENCY
from conector_odoo.config import Settings
from conector_odoo.domain.errors import ProfileValidationError, RemoteAuthError
from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundPolicy
from conector_odoo.domain.profiles import ConnectionProfile, ProfileType, Secrets
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.json2 import Json2Transport
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from conector_odoo.infrastructure.odoo.records import OdooRecordEndpoint
from conector_odoo.infrastructure.odoo.transport import OdooTransport
from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport


def build_transport(settings: Settings) -> OdooTransport:
    if (
        settings.odoo_url is None
        or settings.odoo_db is None
        or settings.odoo_user is None
        or settings.odoo_api_key is None
    ):
        raise ProfileValidationError(
            "ODOO_URL, ODOO_DB, ODOO_USER and ODOO_API_KEY must all be set for the env connection"
        )
    url = settings.odoo_url
    db = settings.odoo_db
    user = settings.odoo_user
    api_key = settings.odoo_api_key.get_secret_value()
    timeout = settings.odoo_timeout_seconds
    retries = settings.odoo_max_retries
    if settings.odoo_protocol == "xmlrpc":
        return XmlRpcTransport(url, db, user, api_key, timeout=timeout, max_retries=retries)
    pool = settings.odoo_max_concurrency
    if settings.odoo_protocol == "json2":
        return Json2Transport(
            url, db, user, api_key, timeout=timeout, max_retries=retries, max_connections=pool
        )
    return JsonRpcTransport(
        url, db, user, api_key, timeout=timeout, max_retries=retries, max_connections=pool
    )


def build_odoo_client(settings: Settings) -> OdooClient:
    return OdooClient(
        build_transport(settings),
        company_id=settings.odoo_company_id,
        max_concurrency=settings.odoo_max_concurrency,
    )


def build_odoo_profile_client(
    profile: ConnectionProfile,
    secrets: Secrets,
    *,
    protocol: Literal["jsonrpc", "xmlrpc", "json2"] = "jsonrpc",
    max_retries: int = 2,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    company_id: int | None = None,
    policy: OutboundPolicy = DEFAULT_POLICY,
) -> OdooClient:
    """``OdooClient`` for an Odoo connection profile (``odoo_db``/``odoo_login``); no I/O.

    The credential is the API key, falling back to the password. Secrets only travel into the
    transport; nothing here logs or ``repr``s them.
    """
    if profile.type is not ProfileType.ODOO:
        raise ProfileValidationError("an Odoo endpoint needs a profile of type odoo")
    if not profile.odoo_db or not profile.odoo_login:
        raise ProfileValidationError("the Odoo database and login are required")
    credential = secrets.api_key or secrets.password
    if not credential:
        raise RemoteAuthError("an API key (or password) is required for this profile")
    url, db, login = profile.base_url.strip(), profile.odoo_db, profile.odoo_login
    timeout = profile.timeout_seconds
    transport: OdooTransport
    if protocol == "xmlrpc":
        transport = XmlRpcTransport(
            url, db, login, credential, timeout=timeout, max_retries=max_retries, policy=policy
        )
    elif protocol == "json2":
        transport = Json2Transport(
            url,
            db,
            login,
            credential,
            timeout=timeout,
            max_retries=max_retries,
            max_connections=max_concurrency,
            policy=policy,
        )
    else:
        transport = JsonRpcTransport(
            url,
            db,
            login,
            credential,
            timeout=timeout,
            max_retries=max_retries,
            max_connections=max_concurrency,
            policy=policy,
        )
    return OdooClient(transport, company_id=company_id, max_concurrency=max_concurrency)


def build_odoo_endpoint(
    profile: ConnectionProfile,
    secrets: Secrets,
    *,
    protocol: Literal["jsonrpc", "xmlrpc", "json2"] = "jsonrpc",
    max_retries: int = 2,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    company_id: int | None = None,
    allow_system_model_writes: bool = False,
    policy: OutboundPolicy = DEFAULT_POLICY,
) -> OdooRecordEndpoint:
    """Generic record endpoint for an Odoo connection profile."""
    client = build_odoo_profile_client(
        profile,
        secrets,
        protocol=protocol,
        max_retries=max_retries,
        max_concurrency=max_concurrency,
        company_id=company_id,
        policy=policy,
    )
    return OdooRecordEndpoint(client, allow_system_model_writes=allow_system_model_writes)
