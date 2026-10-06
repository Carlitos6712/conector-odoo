"""Fernet-based ``SecretVault``: authenticated symmetric encryption of a profile's secrets.

Key rotation uses ``MultiFernet``: the primary key (``ENCRYPTION_KEY``) is the only one that
encrypts; ``ENCRYPTION_KEY_PREVIOUS`` keys are tried, after it, for decryption only. A rotation
(``conector_odoo.manage rotate-vault-key``) rewrites every stored secret under the primary key so
the previous keys can then be dropped.
"""

import json
from collections.abc import Callable, Sequence
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from conector_odoo.config import Settings
from conector_odoo.domain.errors import VaultDecryptionError, VaultNotConfigured
from conector_odoo.domain.profiles import Secrets
from conector_odoo.infrastructure.profiles.key_file import resolve_key

_GENERATE_HINT = (
    'generate one with: python -c "from cryptography.fernet import Fernet; '
    'print(Fernet.generate_key().decode())"'
)

BlobState = Literal["current", "outdated", "undecryptable"]


class FernetVault:
    """Keys come from ``Settings``; there is deliberately no key auto-generation (a silently
    generated key would orphan every secret on the next restart). Neither the keys nor the
    secrets appear in ``repr`` or in any error message."""

    def __init__(
        self, key: str | Callable[[], str | None] | None, previous_keys: Sequence[str] = ()
    ) -> None:
        # A callable is resolved on every use, so a key generated at runtime is picked up
        # without a restart.
        self._key_source = key
        self._previous = tuple(previous_keys)

    def __repr__(self) -> str:
        return f"FernetVault(previous_keys={len(self._previous)})"

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, secrets: Secrets) -> bytes:
        payload = json.dumps(secrets.as_dict(), separators=(",", ":")).encode()
        return self._multi().encrypt(payload)  # MultiFernet encrypts with its first (primary) key

    def decrypt(self, blob: bytes) -> Secrets:
        fernet = self._multi()
        try:
            data = json.loads(fernet.decrypt(blob))
            return Secrets(**data)
        except (InvalidToken, ValueError, TypeError):
            raise VaultDecryptionError(
                "cannot decrypt the stored secrets: no configured key (ENCRYPTION_KEY or "
                "ENCRYPTION_KEY_PREVIOUS) matches the key they were encrypted with, or the data "
                "is corrupted"
            ) from None

    def classify(self, blob: bytes) -> BlobState:
        """``current`` (primary key), ``outdated`` (only a previous key opens it) or
        ``undecryptable``. Raises ``VaultNotConfigured`` when the keys themselves are unusable."""
        primary = self._primary()
        try:
            self.decrypt(blob)
        except VaultDecryptionError:
            return "undecryptable"
        try:
            primary.decrypt(blob)
        except InvalidToken:
            return "outdated"
        return "current"

    def rotate(self, blob: bytes) -> bytes:
        """The same secrets re-encrypted under the primary key. Raises ``VaultDecryptionError``."""
        self.decrypt(blob)  # validates the token AND the payload shape, with the safe error
        return self._multi().rotate(blob)

    @property
    def _key(self) -> str | None:
        source = self._key_source
        return source() if callable(source) else source

    def _primary(self) -> Fernet:
        key = self._key
        if not key:
            raise VaultNotConfigured(f"ENCRYPTION_KEY is not set; {_GENERATE_HINT}")
        try:
            return Fernet(key.encode())
        except ValueError:
            raise VaultNotConfigured(
                f"ENCRYPTION_KEY is not a valid Fernet key; {_GENERATE_HINT}"
            ) from None

    def _multi(self) -> MultiFernet:
        fernets = [self._primary()]
        try:
            fernets.extend(Fernet(old.encode()) for old in self._previous)
        except ValueError:
            raise VaultNotConfigured(
                "ENCRYPTION_KEY_PREVIOUS contains a value that is not a valid Fernet key"
            ) from None
        return MultiFernet(fernets)


def build_vault(settings: Settings) -> FernetVault:
    """The key is resolved lazily: ``ENCRYPTION_KEY`` first, then the key file."""
    return FernetVault(lambda: resolve_key(settings)[0], settings.previous_encryption_keys())
