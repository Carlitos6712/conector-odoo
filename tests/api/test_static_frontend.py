"""Serving the built frontend: SPA fallback that never shadows the API."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conector_odoo.main import create_app
from tests.admin_api.conftest import admin_settings

INDEX_HTML = "<!doctype html><title>spa</title><div id=root></div>"
SECRET = "top-secret-outside-dist"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX_HTML)
    (root / "assets" / "index-abc123.js").write_text("console.log('app')")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text(SECRET)
    return root


def make_client(dist_dir: Path) -> TestClient:
    return TestClient(create_app(admin_settings(frontend_dist_dir=str(dist_dir))))


@pytest.fixture
def client(dist: Path) -> Iterator[TestClient]:
    with make_client(dist) as test_client:
        yield test_client


def test_root_serves_index_without_caching(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/connections", "/runs/42", "/mappings/a/b/c"])
def test_client_side_routes_fall_back_to_index(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert response.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_immutable(client: TestClient) -> None:
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.text == "console.log('app')"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_other_static_files_are_revalidated(client: TestClient) -> None:
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_missing_file_is_a_404_not_the_spa_shell(client: TestClient) -> None:
    for path in ("/assets/missing-1.js", "/robots.txt"):
        response = client.get(path)
        assert response.status_code == 404
        assert INDEX_HTML not in response.text


def test_head_is_supported(client: TestClient) -> None:
    assert client.head("/").status_code == 200


def test_other_methods_on_spa_paths_are_not_found(client: TestClient) -> None:
    assert client.post("/connections", json={}).status_code == 404


def test_existing_routes_are_not_shadowed(client: TestClient) -> None:
    webhook = client.post("/webhooks/odoo", content=b"{}")  # HMAC route answers, never the shell
    assert webhook.status_code in (400, 401, 403, 422)
    docs = client.get("/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    assert client.get("/openapi.json").json()["info"]["title"] == "conector-odoo"
    me = client.get("/admin/api/auth/me")
    assert me.status_code == 401
    assert me.json()["error"]
    # Even paths the API does not define stay API answers, never the HTML shell.
    for path in ("/admin/api/nope", "/admin/api", "/webhooks/unknown", "/docs/oauth2-redirect2"):
        response = client.get(path)
        assert response.status_code in (401, 404), path
        assert INDEX_HTML not in response.text, path
    assert client.post("/admin/api/nope", json={}).status_code in (401, 403, 404)


@pytest.mark.parametrize(
    "path",
    ["/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt", "/..%2fsecret.txt", "/assets/%00"],
)
def test_path_traversal_never_leaks_files(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert SECRET not in response.text
    assert response.status_code in (200, 400, 404)


def test_symlinks_cannot_escape_the_dist_dir(dist: Path) -> None:
    (dist / "leak.txt").symlink_to(dist.parent / "secret.txt")
    with make_client(dist) as client:
        response = client.get("/leak.txt")
    assert SECRET not in response.text
    assert response.status_code == 404


def test_missing_dist_is_harmless_and_logged_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with make_client(tmp_path / "nope") as client:
        assert client.get("/").status_code == 404
        assert client.get("/connections").status_code == 404
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/admin/api/auth/me").status_code == 401
    err = capsys.readouterr().err
    assert err.count("frontend build not found") == 1


def test_dist_built_after_startup_is_picked_up(tmp_path: Path) -> None:
    root = tmp_path / "late"
    with make_client(root) as client:
        assert client.get("/").status_code == 404
        root.mkdir()
        (root / "index.html").write_text(INDEX_HTML)
        assert client.get("/").text == INDEX_HTML
