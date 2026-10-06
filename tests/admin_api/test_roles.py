"""Route-table tests: every /admin/api route is authenticated, role-checked and CSRF-protected."""

import re

import pytest

from conector_odoo.main import create_app
from tests.admin_api.conftest import AdminEnv, admin_settings

SAFE = {"GET", "HEAD", "OPTIONS"}
# Reachable without a session on purpose: they establish or drop one.
PUBLIC = {("POST", "/admin/api/auth/login"), ("POST", "/admin/api/auth/logout")}
# Explicit, tested exception to "writes are admin-only": a user changing their OWN password (any
# role). It still needs a session and CSRF; see test_password_change_api.py for its behaviour.
SELF_SERVICE = {("POST", "/admin/api/auth/password")}
ADMIN_ONLY_PREFIXES = ("/admin/api/users",)


def _routes() -> list[tuple[str, str]]:
    # The OpenAPI document lists every route (admin routes must never opt out of the schema).
    paths = create_app(admin_settings()).openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/admin/api")
        for method in operations
    )


ROUTES = _routes()
MUTATING = [(m, p) for m, p in ROUTES if m not in SAFE and (m, p) not in PUBLIC]
ADMIN_MUTATING = [r for r in MUTATING if r not in SELF_SERVICE]
READS = [(m, p) for m, p in ROUTES if m in SAFE]


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_the_route_table_is_not_empty() -> None:
    assert len(ROUTES) >= 5


@pytest.mark.parametrize(("method", "path"), [r for r in ROUTES if r not in PUBLIC])
def test_every_route_denies_anonymous_callers(admin_env: AdminEnv, method: str, path: str) -> None:
    response = admin_env.client.request(method, _concrete(path), json={})
    assert response.status_code == 401, f"{method} {path} is reachable without a session"
    assert response.json()["error"] == "unauthenticated"


@pytest.mark.parametrize(("method", "path"), ADMIN_MUTATING)
def test_operator_is_denied_on_every_mutating_route(
    operator: AdminEnv, method: str, path: str
) -> None:
    # An empty body: the role check must fire before validation or any work happens.
    response = operator.request(method, _concrete(path), json={})
    assert response.status_code == 403, f"{method} {path} let an operator mutate"
    assert response.json()["error"] == "forbidden"


@pytest.mark.parametrize(("method", "path"), MUTATING)
def test_admin_needs_a_valid_csrf_token_on_every_mutating_route(
    admin: AdminEnv, method: str, path: str
) -> None:
    missing = admin.client.request(method, _concrete(path), json={})
    wrong = admin.client.request(
        method, _concrete(path), json={}, headers={"X-CSRF-Token": "wrong-token"}
    )
    for response in (missing, wrong):
        assert response.status_code == 403, f"{method} {path} skips the CSRF check"
        assert response.json()["error"] == "csrf_invalid"


@pytest.mark.parametrize(("method", "path"), READS)
def test_operator_may_read_except_admin_only_resources(
    operator: AdminEnv, method: str, path: str
) -> None:
    response = operator.request(method, _concrete(path))
    if path.startswith(ADMIN_ONLY_PREFIXES):
        assert response.status_code == 403
    else:
        assert response.status_code not in (401, 403), f"{method} {path}: {response.text}"


def test_the_only_non_admin_write_is_the_self_service_password_change() -> None:
    assert set(MUTATING) >= SELF_SERVICE
    assert len(SELF_SERVICE) == 1


def test_reads_do_not_need_csrf(admin: AdminEnv) -> None:
    assert admin.client.get("/admin/api/auth/me").status_code == 200
    assert admin.client.get("/admin/api/users").status_code == 200
