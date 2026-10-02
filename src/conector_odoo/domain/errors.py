"""Domain errors. The API layer maps them to 401 / 404 / 422 / 502."""


class ConnectorError(Exception):
    """Base class for every error raised by the connector domain."""


class OdooAuthError(ConnectorError):
    """Odoo rejected the credentials or the access rights (HTTP 401)."""


class OdooNotFound(ConnectorError):
    """The requested record does not exist (HTTP 404)."""


class OdooValidationError(ConnectorError):
    """Input or business-rule validation failed (HTTP 422)."""


class OdooUnavailable(ConnectorError):
    """Odoo is unreachable, timed out or answered with an unexpected failure (HTTP 502)."""
