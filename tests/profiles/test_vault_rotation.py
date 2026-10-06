import asyncio
import logging
import sqlite3
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet

from conector_odoo.config import Settings
from conector_odoo.domain.errors import VaultDecryptionError, VaultNotConfigured
from conector_odoo.domain.profiles import AuthMethod, ConnectionProfile, ProfileType, Secrets
from conector_odoo.infrastructure.migrations import open_admin_database
from conector_odoo.infrastructure.profiles.repository import SqliteConnectionProfileRepository
from conector_odoo.infrastructure.profiles.rotation import inspect_vault, rotate_vault
from conector_odoo.infrastructure.profiles.vault import FernetVault

PLAIN = "super-secret-value-123"


def key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


def add_profile(conn: sqlite3.Connection, name: str, blob: bytes | None) -> int:
    profile = ConnectionProfile(
        id=None,
        name=name,
        type=ProfileType.REST,
        base_url="https://api.test",
        auth_method=AuthMethod.BEARER,
    )
    stored = asyncio.run(SqliteConnectionProfileRepository(conn).add(profile, blob))
    assert stored.id is not None
    return stored.id


def blobs(conn: sqlite3.Connection) -> dict[int, bytes | None]:
    return {r[0]: r[1] for r in conn.execute("SELECT id, secrets_blob FROM connection_profiles")}


# -- vault --------------------------------------------------------------------------------------


def test_previous_key_decrypts_and_the_primary_key_encrypts() -> None:
    old, new = key(), key()
    old_blob = FernetVault(old).encrypt(Secrets(token=PLAIN))
    vault = FernetVault(new, previous_keys=[old])
    assert vault.decrypt(old_blob).token == PLAIN
    fresh = vault.encrypt(Secrets(token=PLAIN))
    assert FernetVault(new).decrypt(fresh).token == PLAIN  # encrypted under the primary key only
    with pytest.raises(VaultDecryptionError):
        FernetVault(old).decrypt(fresh)


def test_several_previous_keys_are_all_tried() -> None:
    k1, k2, new = key(), key(), key()
    vault = FernetVault(new, previous_keys=[k1, k2])
    for old in (k1, k2):
        assert vault.decrypt(FernetVault(old).encrypt(Secrets(token=PLAIN))).token == PLAIN


def test_an_unknown_key_still_fails() -> None:
    vault = FernetVault(key(), previous_keys=[key()])
    with pytest.raises(VaultDecryptionError):
        vault.decrypt(FernetVault(key()).encrypt(Secrets(token=PLAIN)))


def test_invalid_previous_key_is_a_clear_error_that_does_not_echo_the_key() -> None:
    bogus = "not-a-key-but-sensitive-looking"
    vault = FernetVault(key(), previous_keys=[bogus])
    with pytest.raises(VaultNotConfigured, match="ENCRYPTION_KEY_PREVIOUS") as info:
        vault.encrypt(Secrets(token=PLAIN))
    assert bogus not in str(info.value)


def test_previous_keys_without_a_primary_key_are_not_enough() -> None:
    with pytest.raises(VaultNotConfigured, match="ENCRYPTION_KEY"):
        FernetVault(None, previous_keys=[key()]).decrypt(b"x")


def test_classify_reports_current_outdated_and_undecryptable() -> None:
    old, new = key(), key()
    vault = FernetVault(new, previous_keys=[old])
    assert vault.classify(vault.encrypt(Secrets(token=PLAIN))) == "current"
    assert vault.classify(FernetVault(old).encrypt(Secrets(token=PLAIN))) == "outdated"
    assert vault.classify(FernetVault(key()).encrypt(Secrets(token=PLAIN))) == "undecryptable"
    assert vault.classify(b"garbage") == "undecryptable"


def test_settings_split_the_comma_separated_previous_keys() -> None:
    k1, k2 = key(), key()
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        odoo_url="https://odoo.test",
        odoo_db="db",
        odoo_user="bot",
        odoo_api_key="a" * 20,
        webhook_secret="w" * 20,
        encryption_key_previous=f" {k1} , ,{k2}",
    )
    assert settings.previous_encryption_keys() == [k1, k2]
    assert k1 not in repr(settings) and k2 not in repr(settings)


# -- rotation -----------------------------------------------------------------------------------


def test_rotation_reencrypts_everything_under_the_primary_key(conn: sqlite3.Connection) -> None:
    old, new = key(), key()
    old_vault = FernetVault(old)
    ids = [
        add_profile(conn, f"p{i}", old_vault.encrypt(Secrets(token=f"{PLAIN}{i}")))
        for i in range(3)
    ]
    current = add_profile(conn, "current", FernetVault(new).encrypt(Secrets(token=PLAIN)))
    add_profile(conn, "nosecret", None)
    vault = FernetVault(new, previous_keys=[old])

    report = rotate_vault(conn, vault)

    assert report.ok and not report.dry_run
    assert (report.total, report.rotated, report.current, report.undecryptable) == (4, 3, 1, ())
    new_only = FernetVault(new)
    stored = blobs(conn)
    for i, pid in enumerate(ids):
        blob = stored[pid]
        assert blob is not None and new_only.decrypt(blob).token == f"{PLAIN}{i}"
    assert new_only.decrypt(stored[current] or b"").token == PLAIN


def test_rotation_is_idempotent(conn: sqlite3.Connection) -> None:
    old, new = key(), key()
    add_profile(conn, "a", FernetVault(old).encrypt(Secrets(token=PLAIN)))
    vault = FernetVault(new, previous_keys=[old])
    assert rotate_vault(conn, vault).rotated == 1
    before = blobs(conn)
    again = rotate_vault(conn, vault)
    assert again.ok and again.rotated == 0 and again.current == 1
    assert blobs(conn) == before  # nothing was rewritten


def test_dry_run_reports_counts_and_writes_nothing(conn: sqlite3.Connection) -> None:
    old, new = key(), key()
    add_profile(conn, "a", FernetVault(old).encrypt(Secrets(token=PLAIN)))
    before = blobs(conn)
    report = rotate_vault(conn, FernetVault(new, previous_keys=[old]), dry_run=True)
    assert report.ok and report.dry_run and report.rotated == 1  # would rotate
    assert blobs(conn) == before


def test_an_undecryptable_secret_refuses_the_whole_rotation(conn: sqlite3.Connection) -> None:
    old, new = key(), key()
    good = add_profile(conn, "good", FernetVault(old).encrypt(Secrets(token=PLAIN)))
    lost = add_profile(conn, "lost", FernetVault(key()).encrypt(Secrets(token=PLAIN)))
    corrupt = add_profile(conn, "corrupt", b"garbage")
    before = blobs(conn)

    report = rotate_vault(conn, FernetVault(new, previous_keys=[old]))

    assert not report.ok
    assert report.undecryptable == (lost, corrupt)
    assert report.rotated == 0
    assert blobs(conn) == before  # the good one was NOT rotated: no partial writes
    assert before[good] is not None


def test_a_failure_while_writing_rolls_everything_back(conn: sqlite3.Connection) -> None:
    old, new = key(), key()
    for name in ("a", "b", "c"):
        add_profile(conn, name, FernetVault(old).encrypt(Secrets(token=PLAIN)))
    conn.execute(
        "CREATE TRIGGER boom BEFORE UPDATE OF secrets_blob ON connection_profiles "
        "WHEN NEW.name = 'c' BEGIN SELECT RAISE(ABORT, 'disk full'); END"
    )
    before = blobs(conn)
    with pytest.raises(sqlite3.DatabaseError):
        rotate_vault(conn, FernetVault(new, previous_keys=[old]))
    assert blobs(conn) == before
    assert not conn.in_transaction


def test_rotation_needs_a_configured_key(conn: sqlite3.Connection) -> None:
    add_profile(conn, "a", FernetVault(key()).encrypt(Secrets(token=PLAIN)))
    with pytest.raises(VaultNotConfigured):
        rotate_vault(conn, FernetVault(None))


def test_rotation_without_any_secrets_is_a_clean_noop(conn: sqlite3.Connection) -> None:
    add_profile(conn, "nosecret", None)
    report = rotate_vault(conn, FernetVault(None, previous_keys=[]), dry_run=True)
    assert report.ok and report.total == 0


def test_keys_and_secrets_are_never_logged(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    old, new = key(), key()
    add_profile(conn, "a", FernetVault(old).encrypt(Secrets(token=PLAIN)))
    add_profile(conn, "lost", FernetVault(key()).encrypt(Secrets(token=PLAIN)))
    vault = FernetVault(new, previous_keys=[old])
    rotate_vault(conn, vault, dry_run=True)
    inspect_vault(conn, vault)
    text = caplog.text + repr(vault) + str(rotate_vault(conn, vault))
    assert old not in text and new not in text and PLAIN not in text


# -- inspection ---------------------------------------------------------------------------------


def test_inspect_is_read_only_and_names_the_undecryptable_profiles(
    conn: sqlite3.Connection,
) -> None:
    old, new = key(), key()
    add_profile(conn, "cur", FernetVault(new).encrypt(Secrets(token=PLAIN)))
    add_profile(conn, "old", FernetVault(old).encrypt(Secrets(token=PLAIN)))
    lost = add_profile(conn, "lost", FernetVault(key()).encrypt(Secrets(token=PLAIN)))
    before = blobs(conn)
    report = inspect_vault(conn, FernetVault(new, previous_keys=[old]))
    assert (report.total, report.current, report.outdated) == (3, 1, 1)
    assert report.undecryptable == (lost,) and not report.ok
    assert blobs(conn) == before
