"""Fernet-based ``SecretVault``: authenticated symmetric encryption of a profile's secrets."""

import json

from cryptography.fernet import Fernet, InvalidToken

from conector_odoo.domain.errors import VaultDecryptionError, VaultNotConfigured
from conector_odoo.domain.profiles import Secrets

_GENERATE_HINT = (
    'generate one with: python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)


class FernetVault:
    """Key comes from ``Settings.encryption_key``; there is deliberately no key auto-generation
    (a silently generated key would orphan every secret on the next restart)."""

    def __init__(self, key: str | None) -> None:
        self._key = key

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, secrets: Secrets) -> bytes:
        payload = json.dumps(secrets.as_dict(), separators=(",", ":")).encode()
        return self._fernet().encrypt(payload)

    def decrypt(self, blob: bytes) -> Secrets:
        fernet = self._fernet()
        try:
            data = json.loads(fernet.decrypt(blob))
            return Secrets(**data)
        except (InvalidToken, ValueError, TypeError):
            raise VaultDecryptionError(
                "cannot decrypt the stored secrets: ENCRYPTION_KEY does not match the key they "
                "were encrypted with, or the data is corrupted"
            ) from None

    def _fernet(self) -> Fernet:
        if not self._key:
            raise VaultNotConfigured(f"ENCRYPTION_KEY is not set; {_GENERATE_HINT}")
        try:
            return Fernet(self._key.encode())
        except ValueError:
            raise VaultNotConfigured(
                f"ENCRYPTION_KEY is not a valid Fernet key; {_GENERATE_HINT}"
            ) from None
