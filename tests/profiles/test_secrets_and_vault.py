import dataclasses

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from conector_odoo.config import Settings
from conector_odoo.domain.errors import VaultDecryptionError, VaultNotConfigured
from conector_odoo.domain.profiles import Secrets
from conector_odoo.infrastructure.profiles.vault import FernetVault

PLAIN = "super-secret-value-123"


def key() -> str:
    return Fernet.generate_key().decode()


def test_vault_round_trip() -> None:
    vault = FernetVault(key())
    blob = vault.encrypt(Secrets(api_key=PLAIN, client_id="cid"))
    assert PLAIN.encode() not in blob
    assert vault.decrypt(blob) == Secrets(api_key=PLAIN, client_id="cid")


def test_wrong_key_fails_to_decrypt() -> None:
    blob = FernetVault(key()).encrypt(Secrets(token=PLAIN))
    with pytest.raises(VaultDecryptionError) as info:
        FernetVault(key()).decrypt(blob)
    assert PLAIN not in str(info.value)


def test_corrupted_blob_fails_to_decrypt() -> None:
    with pytest.raises(VaultDecryptionError):
        FernetVault(key()).decrypt(b"not-a-fernet-token")


@pytest.mark.parametrize("action", ["encrypt", "decrypt"])
def test_missing_key_raises_clear_error(action: str) -> None:
    vault = FernetVault(None)
    with pytest.raises(VaultNotConfigured, match="ENCRYPTION_KEY") as info:
        if action == "encrypt":
            vault.encrypt(Secrets(api_key=PLAIN))
        else:
            vault.decrypt(b"x")
    assert "Fernet.generate_key" in str(info.value)  # tells how to generate one


def test_invalid_key_is_reported_as_not_configured() -> None:
    with pytest.raises(VaultNotConfigured, match="valid Fernet key"):
        FernetVault("short").encrypt(Secrets(api_key=PLAIN))


def test_generate_key_produces_a_usable_key() -> None:
    vault = FernetVault(FernetVault.generate_key())
    assert vault.decrypt(vault.encrypt(Secrets(password="p"))).password == "p"


def test_secrets_never_leak_through_repr_or_str() -> None:
    secrets = Secrets(api_key=PLAIN, client_secret=PLAIN + "2")
    for text in (repr(secrets), str(secrets), f"{secrets}", f"{[secrets]}"):
        assert PLAIN not in text
    assert "api_key" in repr(secrets)  # names of the set fields are fine


def test_secrets_present_fields_and_merge() -> None:
    base = Secrets(api_key="a", token="t")
    merged = base.merged(Secrets(token="t2", client_id="c"))
    assert merged == Secrets(api_key="a", token="t2", client_id="c")  # omitted (None) keeps
    assert base.merged(Secrets(api_key="")).api_key is None  # empty string clears
    assert merged.present_fields() == frozenset({"api_key", "token", "client_id"})


def test_secrets_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        Secrets(api_key="a").api_key = "b"  # type: ignore[misc]


def test_encryption_key_setting_is_secret_and_optional() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        odoo_url="https://odoo.test",
        odoo_db="db",
        odoo_user="bot",
        odoo_api_key="odoo-secret-key-0123",  # type: ignore[arg-type]
        webhook_secret="whsec-test-secret-123",  # type: ignore[arg-type]
    )
    assert settings.encryption_key is None
    with_key = settings.model_copy(update={"encryption_key": SecretStr(PLAIN)})
    assert PLAIN not in repr(with_key)
    assert PLAIN not in with_key.model_dump_json()
