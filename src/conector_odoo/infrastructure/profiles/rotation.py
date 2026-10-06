"""Inspect and rotate the encrypted secrets stored in ``connection_profiles.secrets_blob``.

``rotate_vault`` re-encrypts every secret under the vault's primary key in ONE transaction that
holds the write lock (``BEGIN IMMEDIATE``), so a running app cannot interleave a secret update.
It is all-or-nothing: if any secret cannot be decrypted by any configured key, nothing is written
and the offending profile ids are reported. Rows already under the primary key are left untouched,
which makes a second run a no-op. Reports carry counts and profile ids only, never keys or secrets.
"""

import logging
import sqlite3
from dataclasses import dataclass

from conector_odoo.domain.errors import VaultNotConfigured
from conector_odoo.infrastructure.profiles.vault import FernetVault
from conector_odoo.infrastructure.sync.locks import connection_lock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VaultReport:
    total: int  # profiles that hold secrets
    current: int  # already under the primary key
    outdated: int  # readable only with a previous key
    undecryptable: tuple[int, ...]  # profile ids no configured key can read
    rotated: int = 0  # rewritten (``dry_run``: would be rewritten)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.undecryptable


def _classify(
    rows: list[tuple[int, bytes]], vault: FernetVault
) -> tuple[list[int], list[int], list[int]]:
    current: list[int] = []
    outdated: list[int] = []
    undecryptable: list[int] = []
    for profile_id, blob in rows:
        state = vault.classify(blob)
        {"current": current, "outdated": outdated, "undecryptable": undecryptable}[state].append(
            profile_id
        )
    return current, outdated, undecryptable


def _secret_rows(conn: sqlite3.Connection) -> list[tuple[int, bytes]]:
    return [
        (int(r[0]), bytes(r[1]))
        for r in conn.execute(
            "SELECT id, secrets_blob FROM connection_profiles "
            "WHERE secrets_blob IS NOT NULL ORDER BY id"
        )
    ]


def inspect_vault(conn: sqlite3.Connection, vault: FernetVault) -> VaultReport:
    """Read-only. Raises ``VaultNotConfigured`` when there are secrets but no usable key."""
    with connection_lock(conn):
        rows = _secret_rows(conn)
    current, outdated, undecryptable = _classify(rows, vault) if rows else ([], [], [])
    return VaultReport(len(rows), len(current), len(outdated), tuple(undecryptable))


def rotate_vault(
    conn: sqlite3.Connection, vault: FernetVault, *, dry_run: bool = False
) -> VaultReport:
    """Re-encrypt every secret under the primary key. The connection must be in autocommit mode
    (the admin database is). Raises ``VaultNotConfigured``; a database error rolls back."""
    with connection_lock(conn):
        conn.execute("BEGIN IMMEDIATE")
        try:
            rows = _secret_rows(conn)
            current, outdated, undecryptable = _classify(rows, vault) if rows else ([], [], [])
            report = VaultReport(
                len(rows), len(current), len(outdated), tuple(undecryptable), 0, dry_run
            )
            if undecryptable:
                conn.execute("ROLLBACK")
                return report
            blobs = dict(rows)
            if not dry_run:
                for profile_id in outdated:
                    conn.execute(
                        "UPDATE connection_profiles SET secrets_blob = ? WHERE id = ?",
                        (vault.rotate(blobs[profile_id]), profile_id),
                    )
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
            return VaultReport(
                report.total, report.current, report.outdated, (), len(outdated), dry_run
            )
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


def check_vault_at_startup(conn: sqlite3.Connection, vault: FernetVault) -> None:
    """Log (never raise) whether the stored secrets open with the configured keys. Reports counts
    and profile ids only. A problem here must not stop the service: profiles that do not use the
    unreadable secrets keep working."""
    try:
        report = inspect_vault(conn, vault)
    except VaultNotConfigured:
        logger.warning(
            "vault: profiles hold stored secrets but ENCRYPTION_KEY (or ENCRYPTION_KEY_PREVIOUS) "
            "is missing or invalid; connections that need them will fail"
        )
        return
    except sqlite3.Error:
        logger.exception("vault: could not inspect the stored secrets")
        return
    if report.undecryptable:
        logger.warning(
            "vault: stored secrets cannot be decrypted with the configured keys; add the old key "
            "to ENCRYPTION_KEY_PREVIOUS or re-enter the secrets",
            extra={"profile_ids": list(report.undecryptable)},
        )
    if report.outdated:
        logger.warning(
            "vault: %d profile(s) still use a previous key; run "
            "`python -m conector_odoo.manage rotate-vault-key`",
            report.outdated,
        )
