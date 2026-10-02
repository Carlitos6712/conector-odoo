import stat
import sys
from pathlib import Path

import pytest

from conector_odoo.infrastructure.sqlite import SqliteDatabase, prepare_private_file


async def test_database_runs_schema_executes_and_closes() -> None:
    db = SqliteDatabase(":memory:", "CREATE TABLE t (a TEXT)")
    assert db.execute("INSERT INTO t VALUES (?)", ("x",)) == 1
    await db.close()
    with pytest.raises(Exception, match="closed"):
        db.execute("INSERT INTO t VALUES (?)", ("y",))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_prepare_private_file_creates_0600_file_in_0700_directory(tmp_path: Path) -> None:
    path = tmp_path / "new" / "db.sqlite3"
    prepare_private_file(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
