"""Build the Odoo transport and client selected by ``Settings.odoo_protocol``."""

from conector_odoo.config import Settings
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.json2 import Json2Transport
from conector_odoo.infrastructure.odoo.jsonrpc import JsonRpcTransport
from conector_odoo.infrastructure.odoo.transport import OdooTransport
from conector_odoo.infrastructure.odoo.xmlrpc import XmlRpcTransport


def build_transport(settings: Settings) -> OdooTransport:
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
