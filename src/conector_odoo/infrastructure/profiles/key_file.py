"""Vault key stored in a file (mode 0600) next to the admin database.

Resolution order: ``ENCRYPTION_KEY`` > key file > none. The file is only ever created, never
replaced: generating a key while one exists would orphan the secrets encrypted under it. Key
material is never logged, returned by an API or put in an error message.
"""

import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet

from conector_odoo.config import Settings
from conector_odoo.domain.errors import VaultKeyAlreadyConfigured, VaultNotConfigured

logger = logging.getLogger(__name__)

KeySource = Literal["env", "file"]


class VaultKeyFile:
    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> str | None:
        try:
            raw = self._path.read_text(encoding="utf-8")
            mode = stat.S_IMODE(self._path.stat().st_mode)
        except FileNotFoundError:
            return None
        if mode & 0o077:
            logger.warning(
                "vault key file has group/other permissions; restrict it with chmod 600",
                extra={"path": str(self._path), "permissions": oct(mode)},
            )
        return raw.strip() or None

    def create(self, key: str) -> None:
        """Atomically create the file with mode 0600; ``FileExistsError`` if it exists."""
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".vault-key-")  # 0600, O_EXCL
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(key + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.link(tmp, self._path)  # fails if the target exists, unlike rename
        finally:
            os.unlink(tmp)


def resolve_key(settings: Settings) -> tuple[str | None, KeySource | None]:
    if settings.encryption_key and settings.encryption_key.get_secret_value():
        return settings.encryption_key.get_secret_value(), "env"
    path = settings.vault_key_path()
    key = VaultKeyFile(path).read() if path else None
    return (key, "file") if key else (None, None)


class VaultKeySetup:
    """Status and one-time generation of the vault key, for the admin API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> tuple[bool, KeySource | None]:
        key, source = resolve_key(self._settings)
        return key is not None, source

    def generate(self) -> None:
        if resolve_key(self._settings)[0] is not None:
            raise VaultKeyAlreadyConfigured("a vault key is already configured")
        path = self._settings.vault_key_path()
        if path is None:
            raise VaultNotConfigured("no data directory to store a vault key in")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            VaultKeyFile(path).create(Fernet.generate_key().decode())
        except FileExistsError:
            raise VaultKeyAlreadyConfigured("a vault key is already configured") from None
