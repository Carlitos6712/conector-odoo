import logging
import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from conector_odoo.config import Settings
from conector_odoo.domain.errors import VaultKeyAlreadyConfigured, VaultNotConfigured
from conector_odoo.domain.profiles import Secrets
from conector_odoo.infrastructure.profiles.key_file import VaultKeyFile, VaultKeySetup
from conector_odoo.infrastructure.profiles.vault import FernetVault, build_vault
from tests.api.conftest import make_settings

ENV_KEY = Fernet.generate_key().decode()


def settings_for(tmp_path: Path, **overrides: object) -> Settings:
    return make_settings(admin_db_path=str(tmp_path / "admin.db"), **overrides)


def test_file_is_created_with_mode_0600_and_read_back(tmp_path: Path) -> None:
    store = VaultKeyFile(tmp_path / "vault.key")
    assert store.read() is None
    key = Fernet.generate_key().decode()
    store.create(key)
    assert store.read() == key
    assert stat.S_IMODE(os.stat(tmp_path / "vault.key").st_mode) == 0o600
    assert sorted(p.name for p in tmp_path.iterdir()) == ["vault.key"]  # no temp file left


def test_create_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    store = VaultKeyFile(tmp_path / "vault.key")
    store.create(Fernet.generate_key().decode())
    with pytest.raises(FileExistsError):
        store.create(Fernet.generate_key().decode())


def test_loose_permissions_warn_without_failing_or_leaking(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "vault.key"
    key = Fernet.generate_key().decode()
    path.write_text(key + "\n")
    path.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        assert VaultKeyFile(path).read() == key
    assert any("permissions" in r.getMessage() for r in caplog.records)
    assert key not in caplog.text


def test_blank_file_counts_as_no_key(tmp_path: Path) -> None:
    path = tmp_path / "vault.key"
    path.write_text("  \n")
    assert VaultKeyFile(path).read() is None


def test_env_key_wins_over_the_file(tmp_path: Path) -> None:
    file_key = Fernet.generate_key().decode()
    VaultKeyFile(tmp_path / "vault.key").create(file_key)
    vault = build_vault(settings_for(tmp_path, encryption_key=ENV_KEY))
    blob = vault.encrypt(Secrets(token="x"))
    assert FernetVault(ENV_KEY).decrypt(blob).token == "x"


def test_file_key_is_used_when_no_env_key(tmp_path: Path) -> None:
    file_key = Fernet.generate_key().decode()
    VaultKeyFile(tmp_path / "vault.key").create(file_key)
    blob = build_vault(settings_for(tmp_path)).encrypt(Secrets(token="x"))
    assert FernetVault(file_key).decrypt(blob).token == "x"


def test_vault_picks_up_a_key_generated_after_it_was_built(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    vault = build_vault(settings)
    with pytest.raises(VaultNotConfigured):
        vault.encrypt(Secrets(token="x"))
    VaultKeySetup(settings).generate()
    assert vault.decrypt(vault.encrypt(Secrets(token="x"))).token == "x"


def test_status_reports_the_source(tmp_path: Path) -> None:
    assert VaultKeySetup(settings_for(tmp_path)).status() == (False, None)
    assert VaultKeySetup(settings_for(tmp_path, encryption_key=ENV_KEY)).status() == (True, "env")
    VaultKeySetup(settings_for(tmp_path)).generate()
    assert VaultKeySetup(settings_for(tmp_path)).status() == (True, "file")


def test_generate_refuses_when_a_key_exists(tmp_path: Path) -> None:
    with pytest.raises(VaultKeyAlreadyConfigured):
        VaultKeySetup(settings_for(tmp_path, encryption_key=ENV_KEY)).generate()
    setup = VaultKeySetup(settings_for(tmp_path))
    setup.generate()
    with pytest.raises(VaultKeyAlreadyConfigured):
        setup.generate()


def test_in_memory_database_has_no_key_file(tmp_path: Path) -> None:
    setup = VaultKeySetup(make_settings())
    assert setup.status() == (False, None)
    with pytest.raises(VaultNotConfigured):
        setup.generate()


def test_explicit_key_file_path_is_honoured(tmp_path: Path) -> None:
    target = tmp_path / "keys" / "k"
    (tmp_path / "keys").mkdir()
    VaultKeySetup(settings_for(tmp_path, vault_key_file=str(target))).generate()
    assert target.exists()
