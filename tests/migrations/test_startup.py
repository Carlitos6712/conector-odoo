import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from conector_odoo.config import Settings
from conector_odoo.main import create_app
from tests.api.conftest import make_settings


def test_default_admin_db_path() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        odoo_url="https://odoo.test",
        odoo_db="db",
        odoo_user="bot",
        odoo_api_key="odoo-secret-key-0123",  # type: ignore[arg-type]
        webhook_secret="whsec-test-secret-123",  # type: ignore[arg-type]
    )
    assert settings.admin_db_path == "./data/admin.db"


def test_startup_migrates_the_admin_database(tmp_path: Path) -> None:
    db = tmp_path / "admin.db"
    app = create_app(make_settings(admin_db_path=str(db)))
    with TestClient(app):
        assert app.state.admin_db is not None
    conn = sqlite3.connect(db)
    try:
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations")]
    finally:
        conn.close()
    assert versions == [1]
