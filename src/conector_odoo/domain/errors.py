"""Domain errors. The API layer maps them to 401 / 403 / 404 / 422 / 502."""


class ConnectorError(Exception):
    """Base class for every error raised by the connector domain."""


class OdooAuthError(ConnectorError):
    """Odoo rejected the credentials or the session (HTTP 401).

    Only this error triggers re-authentication in ``OdooClient``.
    """


class OdooPermissionError(ConnectorError):
    """The authenticated user lacks rights for the operation (HTTP 403).

    Deliberately NOT an ``OdooAuthError``: it is raised while Odoo executes the call, so the
    client must never re-authenticate and replay it (replaying ``create`` could duplicate data).
    """


class OdooNotFound(ConnectorError):
    """The requested record does not exist (HTTP 404)."""


class OdooValidationError(ConnectorError):
    """Input or business-rule validation failed (HTTP 422)."""


class OdooUnavailable(ConnectorError):
    """Odoo is unreachable, timed out or answered with an unexpected failure (HTTP 502)."""
