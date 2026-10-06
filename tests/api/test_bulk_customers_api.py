from collections.abc import Iterator

import pytest

from conector_odoo.domain.entities import Customer
from conector_odoo.domain.errors import BatchPartiallyApplied
from tests.api.conftest import API_KEY, ODOO_KEY, Env, build_env, make_settings


@pytest.fixture
def small_env() -> Iterator[Env]:
    yield from build_env(make_settings(bulk_max_items=3))


def seed(env: Env, name: str, email: str) -> None:
    repo = env.customers
    repo.items[repo._next_id] = Customer(id=repo._next_id, name=name, email=email)
    repo._next_id += 1


def test_bulk_mixed_create_update_and_failed(env: Env) -> None:
    seed(env, "Old", "Old@x.io")
    response = env.client.post(
        "/customers/bulk",
        json={
            "match_by": "email",
            "items": [
                {"name": "New", "email": "new@x.io", "country_code": "ES"},
                {"name": "Renamed", "email": "OLD@x.io", "city": "Sevilla"},
                {"name": "Bad", "email": "not-an-email"},
                {"name": "Dup", "email": "NEW@x.io"},
                {"name": "NoMail"},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["created"], body["updated"], body["failed"]) == (2, 1, 2)
    results = body["results"]
    assert [(r["index"], r["status"], r["id"]) for r in results] == [
        (0, "created", 2),
        (1, "updated", 1),
        (2, "failed", None),
        (3, "failed", None),
        (4, "created", 3),
    ]
    assert results[0]["error"] is None
    assert "email" in results[2]["error"]
    assert "not a valid email" in results[2]["error"]
    assert "not-an-email" not in results[2]["error"]  # input is never echoed
    assert "duplicate email" in results[3]["error"]
    assert env.customers.items[1].city == "Sevilla"
    assert env.customers.items[1].name == "Renamed"


def test_match_by_defaults_to_email(env: Env) -> None:
    response = env.client.post(
        "/customers/bulk", json={"items": [{"name": "A", "email": "a@x.io"}]}
    )
    assert response.status_code == 200
    assert response.json()["created"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": []},
        {"items": [{"name": "A"}], "match_by": "vat"},
        {"items": [{"name": "A"}], "extra": 1},
        {"items": "nope"},
        {"items": ["not-an-object"]},
    ],
)
def test_bulk_validates_the_envelope(env: Env, payload: dict[str, object]) -> None:
    response = env.client.post("/customers/bulk", json=payload)
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert env.customers.create_many_calls == []


def test_bulk_over_the_item_limit_is_422_and_nothing_runs(small_env: Env) -> None:
    items = [{"name": f"N{i}", "email": f"n{i}@x.io"} for i in range(4)]
    response = small_env.client.post("/customers/bulk", json={"items": items})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"
    assert "3" in response.json()["detail"]
    assert small_env.customers.create_many_calls == []
    assert small_env.customers.find_calls == []


def test_bulk_at_the_item_limit_is_accepted(small_env: Env) -> None:
    items = [{"name": f"N{i}", "email": f"n{i}@x.io"} for i in range(3)]
    response = small_env.client.post("/customers/bulk", json={"items": items})
    assert response.status_code == 200
    assert response.json()["created"] == 3


def test_bulk_requires_the_api_key(secured_env: Env) -> None:
    body = {"items": [{"name": "A"}]}
    assert secured_env.client.post("/customers/bulk", json=body).status_code == 401
    ok = secured_env.client.post("/customers/bulk", json=body, headers={"X-API-Key": API_KEY})
    assert ok.status_code == 200


def test_bulk_idempotent_replay_does_not_repeat_the_writes(env: Env) -> None:
    body = {"items": [{"name": "A", "email": "a@x.io"}, {"name": "B", "email": "b@x.io"}]}
    headers = {"Idempotency-Key": "bulk-1"}
    first = env.client.post("/customers/bulk", json=body, headers=headers)
    second = env.client.post("/customers/bulk", json=body, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert len(env.customers.create_many_calls) == 1
    assert len(env.customers.items) == 2


def test_bulk_idempotency_key_reused_with_another_body_is_422(env: Env) -> None:
    headers = {"Idempotency-Key": "bulk-2"}
    env.client.post("/customers/bulk", json={"items": [{"name": "A"}]}, headers=headers)
    other = env.client.post("/customers/bulk", json={"items": [{"name": "B"}]}, headers=headers)
    assert other.status_code == 422
    assert other.json()["error"] == "idempotency_key_reused"


def test_bulk_partial_failure_reports_created_ids_and_the_rest_failed(env: Env) -> None:
    env.customers.create_many_error = BatchPartiallyApplied(
        [10, 11], 1, f"chunk 1 failed: timeout {ODOO_KEY}"
    )
    items = [{"name": f"N{i}", "email": f"n{i}@x.io"} for i in range(3)]
    response = env.client.post("/customers/bulk", json={"items": items})
    assert response.status_code == 200
    body = response.json()
    assert (body["created"], body["updated"], body["failed"]) == (2, 0, 1)
    assert [r["id"] for r in body["results"]] == [10, 11, None]
    assert "chunk 1 failed" in body["results"][2]["error"]
    assert ODOO_KEY not in response.text  # scrubbed


def test_bulk_unknown_country_fails_only_that_item(env: Env) -> None:
    response = env.client.post(
        "/customers/bulk",
        json={"items": [{"name": "A", "country_code": "ZZ"}, {"name": "B", "country_code": "ES"}]},
    )
    body = response.json()
    assert [r["status"] for r in body["results"]] == ["failed", "created"]


def test_bulk_does_not_change_the_single_create_endpoint(env: Env) -> None:
    response = env.client.post("/customers", json={"name": "Ada", "email": "ada@x.io"})
    assert response.status_code == 201
    assert response.json()["is_company"] is False
