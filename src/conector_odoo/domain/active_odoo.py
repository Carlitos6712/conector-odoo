"""Which Odoo connection the connector is currently using.

Pure domain: no framework, HTTP or persistence imports.
"""

from enum import StrEnum


class OdooSource(StrEnum):
    """Where the live Odoo connection comes from."""

    PROFILE = "profile"  # an Odoo connection profile activated from the admin UI
    ENV = "env"  # legacy mode: ODOO_URL/ODOO_DB/ODOO_USER/ODOO_API_KEY
    NONE = "none"  # nothing configured yet
