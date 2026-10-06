"""The live Odoo connection of the process: one current client + repositories, swappable.

Requests take a *lease* on the current connection (``acquire``) and release it when done. A swap
(``commit``) installs the new connection in one synchronous step, so no request ever sees a
half-built or closed client; the previous connection is *retired* and closed only once its last
lease is released (or immediately when it is idle). ``aclose`` force-closes everything at shutdown.

Everything runs on the event loop thread: ``acquire``/``release``/``commit`` never ``await``
between reading and writing the state, which is what makes the swap atomic.
"""

import asyncio
import logging
from collections.abc import Callable

from conector_odoo.config import Settings
from conector_odoo.domain.active_odoo import OdooSource
from conector_odoo.domain.errors import OdooNotConfigured
from conector_odoo.domain.ports import CustomerRepository, ProductRepository, SaleOrderRepository
from conector_odoo.domain.profiles import ConnectionProfile, Secrets
from conector_odoo.infrastructure.odoo.client import OdooClient
from conector_odoo.infrastructure.odoo.customer_repository import OdooCustomerRepository
from conector_odoo.infrastructure.odoo.factory import build_odoo_client, build_odoo_profile_client
from conector_odoo.infrastructure.odoo.product_repository import OdooProductRepository
from conector_odoo.infrastructure.odoo.sale_order_repository import OdooSaleOrderRepository

logger = logging.getLogger(__name__)

ProfileClientFactory = Callable[[ConnectionProfile, Secrets], OdooClient]
EnvClientFactory = Callable[[], OdooClient]


class OdooConnection:
    """A client plus the legacy repositories built on it, and where it came from."""

    def __init__(
        self,
        client: OdooClient,
        *,
        customers: CustomerRepository,
        products: ProductRepository,
        orders: SaleOrderRepository,
        source: OdooSource,
        profile_id: int | None = None,
        profile_name: str | None = None,
        base_url: str | None = None,
        db: str | None = None,
        login: str | None = None,
    ) -> None:
        self.client = client
        self.customers = customers
        self.products = products
        self.orders = orders
        self.source = source
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.base_url = base_url
        self.db = db
        self.login = login
        self.leases = 0
        self.retired = False
        self.closed = False

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.client.aclose()


class OdooLease:
    """Pins one connection for the duration of a request; ``release`` is idempotent."""

    def __init__(self, provider: "OdooConnectionProvider", connection: OdooConnection) -> None:
        self._provider = provider
        self.connection = connection
        self._released = False

    @property
    def client(self) -> OdooClient:
        return self.connection.client

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._provider._release(self.connection)


def _origin(url: str) -> str:
    """The URL without any ``user:password@`` part (it is shown in the admin UI)."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    host = rest.rsplit("@", 1)[-1]
    return f"{scheme}://{host}"


class OdooConnectionProvider:
    """Implements the ``OdooRuntime`` port; see the module docstring."""

    def __init__(
        self,
        settings: Settings,
        *,
        profile_client_factory: ProfileClientFactory | None = None,
        env_client_factory: EnvClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._profile_client_factory = profile_client_factory or self._default_profile_client
        self._env_client_factory = env_client_factory or (lambda: build_odoo_client(settings))
        self._current: OdooConnection | None = None
        self._retired: set[OdooConnection] = set()
        self._closers: set[asyncio.Task[None]] = set()

    @property
    def current(self) -> OdooConnection | None:
        return self._current

    # -- building (no I/O) -------------------------------------------------------------------

    def _default_profile_client(self, profile: ConnectionProfile, secrets: Secrets) -> OdooClient:
        settings = self._settings
        return build_odoo_profile_client(
            profile,
            secrets,
            protocol=settings.odoo_protocol,
            max_retries=settings.odoo_max_retries,
            max_concurrency=settings.odoo_max_concurrency,
            company_id=settings.odoo_company_id,
            policy=settings.outbound_policy(),
        )

    def _wrap(self, client: OdooClient, **meta: object) -> OdooConnection:
        batch = self._settings.odoo_batch_size
        return OdooConnection(
            client,
            customers=OdooCustomerRepository(client, batch_size=batch),
            products=OdooProductRepository(client, batch_size=batch),
            orders=OdooSaleOrderRepository(client),
            **meta,  # type: ignore[arg-type]
        )

    def prepare_profile(self, profile: ConnectionProfile, secrets: Secrets) -> OdooConnection:
        client = self._profile_client_factory(profile, secrets)
        return self._wrap(
            client,
            source=OdooSource.PROFILE,
            profile_id=profile.id,
            profile_name=profile.name,
            base_url=_origin(profile.base_url.strip()),
            db=profile.odoo_db,
            login=profile.odoo_login,
        )

    def prepare_env(self) -> OdooConnection | None:
        settings = self._settings
        if not settings.odoo_env_configured():
            return None
        assert settings.odoo_url is not None
        return self._wrap(
            self._env_client_factory(),
            source=OdooSource.ENV,
            base_url=_origin(settings.odoo_url.strip()),
            db=settings.odoo_db,
            login=settings.odoo_user,
        )

    # -- leasing -----------------------------------------------------------------------------

    def try_acquire(self) -> OdooLease | None:
        connection = self._current
        if connection is None:
            return None
        connection.leases += 1
        return OdooLease(self, connection)

    def acquire(self) -> OdooLease:
        lease = self.try_acquire()
        if lease is None:
            raise OdooNotConfigured(
                "No Odoo connection is configured. Create an Odoo connection profile in the "
                "admin UI and activate it."
            )
        return lease

    def _release(self, connection: OdooConnection) -> None:
        connection.leases -= 1
        if connection.retired and connection.leases <= 0:
            self._close_in_background(connection)

    # -- swapping ----------------------------------------------------------------------------

    async def commit(self, prepared: object | None) -> None:
        """Install ``prepared`` (or ``None`` to disconnect); retire the previous connection."""
        assert prepared is None or isinstance(prepared, OdooConnection)
        old, self._current = self._current, prepared  # one synchronous step: atomic
        if old is None:
            return
        old.retired = True
        self._retired.add(old)
        if old.leases <= 0:
            await self._close_quietly(old)

    async def discard(self, prepared: object) -> None:
        assert isinstance(prepared, OdooConnection)
        await self._close_quietly(prepared)

    def _close_in_background(self, connection: OdooConnection) -> None:
        task = asyncio.get_running_loop().create_task(self._close_quietly(connection))
        self._closers.add(task)
        task.add_done_callback(self._closers.discard)

    async def _close_quietly(self, connection: OdooConnection) -> None:
        self._retired.discard(connection)
        try:
            await connection.aclose()
        except Exception:
            logger.exception("closing an Odoo client failed")

    async def drain(self) -> None:
        """Wait for background closes already scheduled (used by tests and shutdown)."""
        while pending := [task for task in self._closers if not task.done()]:
            await asyncio.wait(pending)
        self._closers.clear()

    async def aclose(self) -> None:
        """Close the current and every retired connection, leased or not (shutdown)."""
        current, self._current = self._current, None
        pending = list(self._retired)
        if current is not None:
            pending.append(current)
        first_error: Exception | None = None
        for connection in pending:
            self._retired.discard(connection)
            try:
                await connection.aclose()
            except Exception as exc:
                logger.exception("closing an Odoo client failed")
                first_error = first_error or exc
        await self.drain()
        if first_error is not None:
            raise first_error  # every client was attempted; surface the failure to the caller
