"""Transport port for talking to Odoo."""

from typing import Any, Protocol


class OdooTransport(Protocol):
    """Low-level Odoo RPC transport.

    Design note: the *transport owns the session credentials*. ``authenticate`` stores whatever
    the protocol needs (the numeric uid for JSON-RPC and XML-RPC) and returns it; ``execute_kw``
    then needs no uid parameter. A ``json2`` transport (Bearer API key, no uid, POST
    ``/json/2/{model}/{method}``) fits behind the same Protocol: its ``authenticate`` can verify
    the key and return a placeholder uid, and its ``execute_kw`` maps ``args``/``kwargs`` onto the
    JSON body. ``OdooClient`` only caches the uid it was handed and decides *when* to
    (re-)authenticate; it never passes it back to the transport.

    Implementations raise domain errors (``OdooAuthError``, ``OdooNotFound``,
    ``OdooValidationError``, ``OdooUnavailable``) and must never put secrets in messages.
    """

    async def authenticate(self) -> int: ...

    async def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any: ...

    async def aclose(self) -> None: ...
