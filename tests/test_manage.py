import asyncio
import io
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from conector_odoo import manage
from conector_odoo.config import Settings
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType, Secrets
from conector_odoo.infrastructure.migrations import close_admin_database, open_admin_database
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.vault import FernetVault
from conector_odoo.main import create_app
from tests.api.conftest import make_settings

PLAIN = "super-secret-value-123"


def key() -> str:
    return Fernet.generate_key().decode()


class World:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.old, self.new = key(), key()
        self.ids: dict[str, int] = {}

    def add(self, name: str, encrypt_key: str | None) -> int:
        conn = open_admin_database(str(self.path))
        blob = FernetVault(encrypt_key).encrypt(Secrets(token=PLAIN)) if encrypt_key else None
        profile = ConnectionProfile(
            id=None,
            name=name,
            type=ProfileType.REST,
            base_url="https://api.test",
            auth_method=AuthMethod.BEARER,
        )
        stored = asyncio.run(SqliteConnectionProfileRepository(conn).add(profile, blob))
        close_admin_database(conn)
        assert stored.id is not None
        self.ids[name] = stored.id
        return stored.id

    def blobs(self) -> dict[int, bytes | None]:
        conn = open_admin_database(str(self.path))
        rows = conn.execute("SELECT id, secrets_blob FROM connection_profiles").fetchall()
        close_admin_database(conn)
        return {r[0]: r[1] for r in rows}

    def settings(self, **overrides: object) -> Settings:
        values: dict[str, object] = {
            "admin_db_path": str(self.path),
            "encryption_key": self.new,
            "encryption_key_previous": self.old,
        }
        values.update(overrides)
        return make_settings(**values)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path / "admin.db")


def run(world: World, *argv: str, **overrides: object) -> tuple[int, str]:
    out = io.StringIO()
    code = manage.main(list(argv), settings=world.settings(**overrides), out=out)
    return code, out.getvalue()


def test_rotate_reencrypts_and_reports_counts(world: World) -> None:
    for name in ("a", "b"):
        world.add(name, world.old)
    world.add("c", world.new)
    code, output = run(world, "rotate-vault-key")
    assert code == 0
    assert "3 profile(s) with secrets" in output and "rotated 2" in output
    new_only = FernetVault(world.new)
    assert all(new_only.decrypt(b or b"").token == PLAIN for b in world.blobs().values())
    assert "ENCRYPTION_KEY_PREVIOUS can be removed" in output


def test_dry_run_changes_nothing(world: World) -> None:
    world.add("a", world.old)
    before = world.blobs()
    code, output = run(world, "rotate-vault-key", "--dry-run")
    assert code == 0 and "dry run" in output and "would rotate 1" in output
    assert world.blobs() == before


def test_second_run_is_a_noop(world: World) -> None:
    world.add("a", world.old)
    run(world, "rotate-vault-key")
    before = world.blobs()
    code, output = run(world, "rotate-vault-key")
    assert code == 0 and "rotated 0" in output
    assert world.blobs() == before


def test_wrong_key_is_refused_with_the_profile_ids_and_no_partial_write(world: World) -> None:
    world.add("good", world.old)
    lost = world.add("lost", key())
    before = world.blobs()
    code, output = run(world, "rotate-vault-key")
    assert code == 1
    assert "REFUSED" in output and str(lost) in output and "Nothing was changed" in output
    assert world.blobs() == before


def test_output_never_contains_keys_or_secrets(world: World) -> None:
    world.add("a", world.old)
    world.add("lost", key())
    _, refused = run(world, "rotate-vault-key")
    _, checked = run(world, "check-vault")
    for text in (refused, checked):
        assert PLAIN not in text and world.old not in text and world.new not in text


def test_check_vault_reports_without_writing(world: World) -> None:
    world.add("cur", world.new)
    world.add("old", world.old)
    before = world.blobs()
    code, output = run(world, "check-vault")
    assert code == 0 and "1 under the primary key" in output and "1 under a previous key" in output
    assert world.blobs() == before


def test_check_vault_fails_when_a_secret_is_unreadable(world: World) -> None:
    lost = world.add("lost", key())
    code, output = run(world, "check-vault")
    assert code == 1 and str(lost) in output


def test_missing_key_is_a_configuration_error(world: World) -> None:
    world.add("a", world.old)
    code, output = run(world, "rotate-vault-key", encryption_key=None)
    assert code == 2 and "ENCRYPTION_KEY" in output


def test_missing_database_is_reported_and_not_created(world: World) -> None:
    code, output = run(world, "check-vault")
    assert code == 2 and "not found" in output
    assert not world.path.exists()


def test_unknown_command_is_a_usage_error(world: World) -> None:
    with pytest.raises(SystemExit) as info:
        run(world, "nope")
    assert info.value.code == 2


# -- startup check ------------------------------------------------------------------------------


class Capture(logging.Handler):
    """create_app reconfigures the root logger (dropping caplog's handler), so listen directly."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        return "\n".join(r.getMessage() for r in self.records)


@pytest.fixture
def started(world: World) -> Iterator[World]:
    yield world


@pytest.fixture
def caplog() -> Iterator[Capture]:  # shadows the built-in fixture on purpose, see Capture
    handler = Capture()
    logger = logging.getLogger("conector_odoo.infrastructure.profiles.rotation")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    yield handler
    logger.removeHandler(handler)


def test_startup_warns_about_unreadable_secrets_without_failing(
    started: World, caplog: Capture
) -> None:
    lost = started.add("lost", key())
    started.add("old", started.old)
    with TestClient(create_app(started.settings(admin_bootstrap_user=None))):
        pass
    records = [r for r in caplog.records if "cannot be decrypted" in r.getMessage()]
    assert records and records[0].levelno == logging.WARNING
    assert getattr(records[0], "profile_ids", None) == [lost]
    assert (
        started.old not in caplog.text
        and started.new not in caplog.text
        and PLAIN not in caplog.text
    )
    assert any("previous key" in r.getMessage() for r in caplog.records)


def test_startup_is_quiet_when_everything_is_current(started: World, caplog: Capture) -> None:
    started.add("cur", started.new)
    with TestClient(create_app(started.settings())):
        pass
    assert not [
        r for r in caplog.records if r.levelno >= logging.WARNING and "vault" in r.getMessage()
    ]


def test_startup_warns_when_the_key_is_missing_but_secrets_exist(
    started: World, caplog: Capture
) -> None:
    started.add("a", started.old)
    with TestClient(create_app(started.settings(encryption_key=None))):
        pass
    assert any("ENCRYPTION_KEY" in r.getMessage() for r in caplog.records)
