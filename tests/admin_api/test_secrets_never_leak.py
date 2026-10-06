"""No admin response, error included, may carry a stored or submitted credential."""

import re

import pytest

from tests.admin_api.conftest import ADMIN_PASSWORD, AdminEnv
from tests.admin_api.test_profiles_api import PROFILES, rest_body
from tests.admin_api.test_roles import ROUTES

SECRETS = {
    "api_key": "API-KEY-SECRET-0123456789",
    "token": "TOKEN-SECRET-0123456789",
    "client_id": "CLIENT-ID-SECRET-0123456789",
    "client_secret": "CLIENT-SECRET-0123456789",
    "password": "PASSWORD-SECRET-0123456789",
}
GETS = [path for method, path in ROUTES if method == "GET"]


@pytest.mark.parametrize("path", GETS)
def test_no_read_route_returns_a_credential(admin: AdminEnv, path: str) -> None:
    assert admin.post(PROFILES, json=rest_body(secrets=SECRETS)).status_code == 201
    response = admin.get(re.sub(r"\{[^}]+\}", "1", path))
    for value in [*SECRETS.values(), ADMIN_PASSWORD]:
        assert value not in response.text
    assert "argon2" not in response.text and "secrets_blob" not in response.text


def test_error_and_validation_responses_do_not_echo_credentials(admin: AdminEnv) -> None:
    duplicate = admin.post(PROFILES, json=rest_body(secrets=SECRETS))
    again = admin.post(PROFILES, json=rest_body(secrets=SECRETS))
    invalid = admin.post(
        PROFILES, json=rest_body(name="x", timeout_seconds="oops", secrets=SECRETS)
    )
    unknown_field = admin.post(
        PROFILES, json=rest_body(name="y", secrets={**SECRETS, "bogus": "S3CRET-VALUE"})
    )
    for response in (duplicate, again, invalid, unknown_field):
        for value in [*SECRETS.values(), "S3CRET-VALUE"]:
            assert value not in response.text


def test_failed_logins_do_not_echo_the_submitted_password(admin_env: AdminEnv) -> None:
    response = admin_env.client.post(
        "/admin/api/auth/login", json={"username": "root", "password": "wrong-PASSWORD-9876543"}
    )
    assert "wrong-PASSWORD" not in response.text
