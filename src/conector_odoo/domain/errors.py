"""Domain errors. The API layer maps them to 401 / 403 / 404 / 422 / 502 (and 202 for
``CreatedButUnreadable``; ``BatchPartiallyApplied`` is a 502 that lists the created ids)."""


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


class CreatedButUnreadable(ConnectorError):
    """A ``create`` succeeded in Odoo but the new record could not be read back.

    The record exists, so callers must not blindly retry the create: the error carries the
    ``model`` and ``record_id`` so the API can answer 202 with a pointer to the resource.
    """

    def __init__(self, model: str, record_id: int, message: str) -> None:
        super().__init__(message)
        self.model = model
        self.record_id = record_id


class BatchPartiallyApplied(ConnectorError):
    """A chunked ``create`` failed after earlier chunks were already created in Odoo.

    Chunks are separate, non-idempotent calls that are never retried, so the records created
    before the failure exist. ``created_ids`` lists them in input order (the first
    ``len(created_ids)`` input items were applied) and ``failed_chunk`` is the zero-based index
    of the chunk that failed. The original error is available as ``__cause__``.
    """

    def __init__(self, created_ids: list[int], failed_chunk: int, message: str) -> None:
        super().__init__(message)
        self.created_ids = list(created_ids)
        self.failed_chunk = failed_chunk


class ProfileNotFound(ConnectorError):
    """No connection profile with the requested id."""


class ProfileNameTaken(ConnectorError):
    """Another connection profile already uses that (unique) name."""


class ProfileInUse(ConnectorError):
    """The profile is referenced by resources or jobs and cannot be deleted."""


class ProfileValidationError(ConnectorError):
    """The profile data is invalid (empty name, non-positive timeout, ...)."""


class VaultError(ConnectorError):
    """Base class for secret vault failures. Messages never contain secret material."""


class VaultNotConfigured(VaultError):
    """A secret must be encrypted/decrypted but no usable ``ENCRYPTION_KEY`` is configured."""


class VaultDecryptionError(VaultError):
    """A stored secret cannot be decrypted (wrong ``ENCRYPTION_KEY`` or corrupted data)."""
