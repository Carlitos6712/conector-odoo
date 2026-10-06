import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conector_odoo import main as main_module
from conector_odoo.config import Settings
from conector_odoo.infrastructure.api.dependencies import Container, build_container
from conector_odoo.infrastructure.migrations import MIGRATIONS
from conector_odoo.main import create_app
from tests.api.conftest import make_settings


def test_default_admin_db_path() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        odoo_url="https://odoo.test",
        odoo_db="db",
        odoo_user="bot",
        odoo_api_key="odoo-secret-key-0123",  # type: ignore[arg-type]
        webhook_secret="whsec-test-secret-123",  # type: ignore[arg-type]
    )
    assert settings.admin_db_path == "./data/admin.db"


def test_startup_migrates_the_admin_database(tmp_path: Path) -> None:
    db = tmp_path / "admin.db"
    app = create_app(make_settings(admin_db_path=str(db)))
    with TestClient(app):
        assert app.state.admin_db is not None
    conn = sqlite3.connect(db)
    try:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    finally:
        conn.close()
    assert versions == [m.version for m in MIGRATIONS]


def test_admin_database_failure_closes_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[Container] = []

    def spy_build(settings: Settings) -> Container:
        built.append(build_container(settings))
        return built[0]

    def broken_open(path: str) -> sqlite3.Connection:
        raise RuntimeError("admin db unavailable")

    monkeypatch.setattr(main_module, "build_container", spy_build)
    monkeypatch.setattr(main_module, "open_admin_database", broken_open)
    app = create_app(make_settings(idempotency_db_path=str(tmp_path / "idem.db")))
    with pytest.raises(RuntimeError, match="admin db unavailable"), TestClient(app):
        pass
    with pytest.raises(sqlite3.ProgrammingError):  # closed connection: the stores were released
        built[0].idempotency._conn.execute("SELECT 1")  # type: ignore[attr-defined]


def test_closing_the_admin_database_waits_for_statements_in_worker_threads() -> None:
    """A cancelled await leaves its worker thread running; close must not free the connection
    under it (that crashed the interpreter in the full test suite)."""
    import threading
    import time

    from conector_odoo.infrastructure.migrations import close_admin_database, open_admin_database
    from conector_odoo.infrastructure.sync.locks import connection_lock

    conn = open_admin_database(":memory:")
    closed = threading.Event()
    with connection_lock(conn):  # a repository statement is "running"
        closer = threading.Thread(target=lambda: (close_admin_database(conn), closed.set()))
        closer.start()
        time.sleep(0.2)
        assert not closed.is_set()
    closer.join(5)
    assert closed.is_set()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_admin_connection_is_autocommit_so_repository_writes_are_durable(tmp_path: Path) -> None:
    """Repositories never commit: that relies on ``isolation_level=None`` (autocommit)."""
    import asyncio

    from conector_odoo.domain.mapping import Constant, MappingDefinition, MappingRule
    from conector_odoo.infrastructure.mappings.repository import SqliteMappingRepository
    from conector_odoo.infrastructure.migrations import close_admin_database, open_admin_database

    path = tmp_path / "admin.db"
    conn = open_admin_database(str(path))
    try:
        assert conn.isolation_level is None
        definition = MappingDefinition("m", "a", "b", (MappingRule("x", Constant(1)),))
        asyncio.run(SqliteMappingRepository(conn).save_new_version(definition))
        other = sqlite3.connect(path)  # a second connection sees it without any explicit commit
        try:
            assert other.execute("SELECT COUNT(*) FROM mappings").fetchone() == (1,)
        finally:
            other.close()
    finally:
        close_admin_database(conn)
