"""Management commands: ``python -m conector_odoo.manage <command>``.

* ``check-vault``: report (read-only) how many stored secrets are under the primary key, under a
  previous key, or unreadable.
* ``rotate-vault-key [--dry-run]``: re-encrypt every stored secret under ``ENCRYPTION_KEY``. See
  ``infrastructure/profiles/rotation.py`` for the guarantees (single transaction, all-or-nothing,
  idempotent).

Exit codes: 0 success, 1 refused because some secret is unreadable, 2 configuration or usage
error. Output has counts and profile ids only: never keys or secrets.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from conector_odoo.config import Settings
from conector_odoo.domain.errors import VaultNotConfigured
from conector_odoo.infrastructure.migrations import close_admin_database, open_admin_database
from conector_odoo.infrastructure.profiles.rotation import (
    VaultReport,
    inspect_vault,
    rotate_vault,
)
from conector_odoo.infrastructure.profiles.vault import build_vault

EXIT_OK, EXIT_REFUSED, EXIT_CONFIG = 0, 1, 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m conector_odoo.manage")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-vault", help="report which stored secrets the configured keys open")
    rotate = commands.add_parser(
        "rotate-vault-key", help="re-encrypt every stored secret under ENCRYPTION_KEY"
    )
    rotate.add_argument(
        "--dry-run", action="store_true", help="report what would change and write nothing"
    )
    return parser


def _summary(report: VaultReport) -> str:
    return (
        f"vault: {report.total} profile(s) with secrets: {report.current} under the primary key, "
        f"{report.outdated} under a previous key, {len(report.undecryptable)} unreadable"
    )


def _ids(report: VaultReport) -> str:
    return ", ".join(str(i) for i in report.undecryptable)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    out: TextIO | None = None,
) -> int:
    args = _parser().parse_args(argv)
    stream = out or sys.stdout

    def say(line: str) -> None:
        print(line, file=stream)

    try:
        resolved = settings or Settings()
    except ValidationError as exc:
        fields = ", ".join(sorted({str(e["loc"][0]).upper() for e in exc.errors() if e["loc"]}))
        say(f"invalid configuration: check {fields or 'the environment'}")
        return EXIT_CONFIG
    path = resolved.admin_db_path
    if path != ":memory:" and not Path(path).exists():
        say("the admin database was not found (check ADMIN_DB_PATH); nothing was changed")
        return EXIT_CONFIG
    vault = build_vault(resolved)
    conn = open_admin_database(path)
    try:
        if args.command == "check-vault":
            report = inspect_vault(conn, vault)
        else:
            report = rotate_vault(conn, vault, dry_run=args.dry_run)
    except VaultNotConfigured as exc:
        say(f"cannot use the vault keys: {exc}")
        return EXIT_CONFIG
    finally:
        close_admin_database(conn)
    say(_summary(report))
    if not report.ok:
        action = "Nothing was changed. " if args.command == "rotate-vault-key" else ""
        say(
            f"REFUSED: no configured key can decrypt the secrets of profile id(s): {_ids(report)}. "
            f"{action}Add the key they were encrypted with to ENCRYPTION_KEY_PREVIOUS, or re-enter "
            "those secrets in the UI, then try again."
        )
        return EXIT_REFUSED
    if args.command == "rotate-vault-key":
        if report.dry_run:
            say(f"dry run: would rotate {report.rotated} profile(s); nothing was written")
        else:
            say(f"rotated {report.rotated} profile(s)")
            if report.total == report.current + report.rotated:
                say("every secret is under the primary key: ENCRYPTION_KEY_PREVIOUS can be removed")
    elif report.outdated:
        say("run `rotate-vault-key` to move them under ENCRYPTION_KEY")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
