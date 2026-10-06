"""Domain errors. The API layer maps them to 401 / 403 / 404 / 422 / 502 (and 202 for
``CreatedButUnreadable``; ``BatchPartiallyApplied`` is a 502 that lists the created ids)."""

from collections.abc import Mapping


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


class ResourceNotFound(ConnectorError):
    """The remote system has no such resource (model, endpoint, collection)."""


class RecordRejected(ConnectorError):
    """The remote system refused a record (validation or business rule).

    ``field_errors`` maps field names to the remote's message when it reports them.
    """

    def __init__(self, message: str, field_errors: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.field_errors: dict[str, str] = dict(field_errors or {})


class RemoteUnavailable(ConnectorError):
    """The remote system is unreachable, timed out or failed unexpectedly."""


class RemoteAuthError(ConnectorError):
    """The remote system rejected the credentials or the session."""


class ResourceConfigInvalid(ConnectorError):
    """A REST resource configuration is malformed (bad endpoint, inconsistent pagination, or
    stored JSON that is unknown or corrupt)."""


class CatalogResourceNotFound(ConnectorError):
    """The resource catalog of a profile has no entry with that name."""


class OpenApiImportError(ConnectorError):
    """An OpenAPI/Swagger document cannot be fetched or parsed (too large, bad scheme, not a
    supported document)."""


class MappingInvalid(ConnectorError):
    """A stored or submitted mapping document is malformed (unknown expression or step type,
    wrong field types, unsupported schema version); the message names the offending path."""


class MappingNotFound(ConnectorError):
    """No saved mapping with that name (or version)."""


class MappingInUse(ConnectorError):
    """The mapping is referenced by a sync job and cannot be deleted."""


class SyncJobNotFound(ConnectorError):
    """No sync job with the requested id."""


class SyncJobNameTaken(ConnectorError):
    """Another sync job already uses that (unique) name."""


class SyncJobInUse(ConnectorError):
    """The job has runs (history) and cannot be deleted."""


class SyncJobInvalid(ConnectorError):
    """The sync job definition is invalid (batch size, upsert key, trigger, conflict rule...)."""


class SyncRunNotFound(ConnectorError):
    """No sync run with the requested id."""


class JobAlreadyRunning(ConnectorError):
    """The job already has an active run; only one run per job may be active at a time."""


class RunNotResumable(ConnectorError):
    """The run cannot be resumed or retried in its current state."""


class AuthenticationFailed(ConnectorError):
    """Wrong username or password. Deliberately says nothing about which one."""


class CurrentPasswordInvalid(ConnectorError):
    """A self-service password change supplied the wrong current password."""


class LoginLocked(ConnectorError):
    """Too many failed logins for this username; retry after ``retry_after_seconds``."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("too many failed login attempts; try again later")
        self.retry_after_seconds = retry_after_seconds


class SessionInvalid(ConnectorError):
    """The session is unknown, expired or was rotated away."""


class AdminUserNotFound(ConnectorError):
    """No admin user with the requested id."""


class AdminUsernameTaken(ConnectorError):
    """Another admin user already has that (case-insensitive) username."""


class AdminUserInvalid(ConnectorError):
    """The admin user data is invalid (empty username, weak password, unknown role)."""


class LastAdminError(ConnectorError):
    """The operation would leave the system without an administrator."""


class AdminForbidden(ConnectorError):
    """The signed-in admin user's role does not allow this operation."""


class CsrfInvalid(ConnectorError):
    """A state-changing admin request lacks a valid CSRF token."""
