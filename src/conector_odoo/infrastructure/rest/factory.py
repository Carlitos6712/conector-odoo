"""Builds a ready-to-use ``RestRecordEndpoint`` from a connection profile and its secrets."""

from typing import Any

from conector_odoo.domain.outbound import DEFAULT_POLICY, OutboundPolicy
from conector_odoo.domain.ports import ResourceConfigProvider
from conector_odoo.domain.profiles import ConnectionProfile, Secrets
from conector_odoo.infrastructure.rest.auth import build_authenticator
from conector_odoo.infrastructure.rest.endpoint import RestRecordEndpoint
from conector_odoo.infrastructure.rest.http import RestHttpClient


def build_rest_endpoint(
    profile: ConnectionProfile,
    secrets: Secrets,
    configs: ResourceConfigProvider,
    *,
    issuer_url: str | None = None,
    policy: OutboundPolicy = DEFAULT_POLICY,
    **http_options: Any,
) -> RestRecordEndpoint:
    """``http_options`` are ``RestHttpClient`` tuning knobs (``max_retries``, ``min_interval``,
    ``idempotency_header``, ...). Timeout, TLS verification and extra headers come from the
    profile. The caller owns the result and must ``aclose()`` it."""
    auth = build_authenticator(profile, secrets, issuer_url=issuer_url)
    http = RestHttpClient(
        profile.base_url,
        auth,
        extra_headers=profile.extra_headers,
        tls_verify=profile.tls_verify,
        policy=policy,
        timeout=profile.timeout_seconds,
        **http_options,
    )
    return RestRecordEndpoint(http, configs)
