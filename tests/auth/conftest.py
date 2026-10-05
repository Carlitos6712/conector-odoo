import sqlite3
from collections.abc import Iterator

import pytest

from conector_odoo.infrastructure.migrations import open_admin_database
from tests.auth.helpers import AuthWorld


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    connection = open_admin_database(":memory:")
    yield connection
    connection.close()


@pytest.fixture
def world(conn: sqlite3.Connection) -> AuthWorld:
    return AuthWorld(conn)
