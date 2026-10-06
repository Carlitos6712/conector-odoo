import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from conector_odoo.domain.errors import SyncJobInvalid
from conector_odoo.domain.records import RecordFilter
from conector_odoo.domain.sync import (
    ConflictRule,
    Direction,
    ManualTrigger,
    ScheduleTrigger,
    TriggerKind,
    WebhookTrigger,
)
from conector_odoo.domain.sync_runs import RunCounters, RunStatus, redact_payload
from tests.sync.helpers import make_job


def test_valid_job_defaults() -> None:
    job = make_job()
    assert job.direction is Direction.A_TO_B
    assert job.trigger.kind is TriggerKind.MANUAL
    assert job.mapping.version is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "  "},
        {"batch_size": 0},
        {"batch_size": 1001},
        {"upsert_key": "email"},
        {"upsert_key": "field:"},
        {"direction": Direction.BIDIRECTIONAL, "reverse_mapping": None},
        {"direction": Direction.B_TO_A, "reverse_mapping": None},
        {"conflict_rule": ConflictRule.NEWEST_WINS},
        {"conflict_rule": ConflictRule.NEWEST_WINS, "source_updated_field": "w"},
    ],
)
def test_invalid_jobs_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(SyncJobInvalid):
        make_job(**overrides)


def test_boundary_batch_sizes_and_field_key_are_accepted() -> None:
    assert make_job(batch_size=1).batch_size == 1
    assert make_job(batch_size=1000, upsert_key="field:email").upsert_key == "field:email"


def test_newest_wins_needs_both_updated_fields() -> None:
    job = make_job(
        conflict_rule=ConflictRule.NEWEST_WINS,
        source_updated_field="write_date",
        target_updated_field="updated",
    )
    assert job.target_updated_field == "updated"


def test_bidirectional_with_reverse_mapping_is_valid() -> None:
    assert make_job(direction=Direction.BIDIRECTIONAL).reverse_mapping is not None


def test_one_way_forward_job_may_not_carry_a_reverse_mapping_requirement() -> None:
    assert make_job(direction=Direction.A_TO_B).reverse_mapping is None


@pytest.mark.parametrize("cron", ["*/5 * * * *", "0 3 * * 1-5", "0,30 8-18 1 1 *", "15 14 1 * 0"])
def test_valid_cron(cron: str) -> None:
    assert ScheduleTrigger(cron).cron == cron


@pytest.mark.parametrize(
    "cron", ["", "* * * *", "60 * * * *", "* 24 * * *", "a b c d e", "*/0 * * * *", "5-1 * * * *"]
)
def test_invalid_cron(cron: str) -> None:
    with pytest.raises(SyncJobInvalid):
        ScheduleTrigger(cron)


def test_webhook_trigger_needs_event_types() -> None:
    assert WebhookTrigger(("customer.updated",)).kind is TriggerKind.WEBHOOK
    with pytest.raises(SyncJobInvalid):
        WebhookTrigger(())
    with pytest.raises(SyncJobInvalid):
        WebhookTrigger(("",))


def test_job_is_immutable() -> None:
    job = make_job(record_filter=RecordFilter(since=datetime(2026, 1, 1, tzinfo=UTC)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        job.name = "x"  # type: ignore[misc]
    assert isinstance(ManualTrigger().kind, TriggerKind)


def test_redact_payload_masks_secrets_recursively_and_bounds_size() -> None:
    payload = {
        "name": "Ana",
        "password": "hunter2",
        "profile": {"api_key": "k", "Authorization": "Bearer x", "city": "Lima"},
        "items": [{"client_secret": "s", "sku": "a"}],
        "bio": "x" * 5000,
    }
    clean = redact_payload(payload)
    assert clean["password"] == "***"
    assert clean["profile"] == {"api_key": "***", "Authorization": "***", "city": "Lima"}
    assert clean["items"] == [{"client_secret": "***", "sku": "a"}]
    assert len(clean["bio"]) < 600
    assert "hunter2" not in repr(clean)


def test_counters_and_status_helpers() -> None:
    counters = RunCounters(created=1, updated=2, skipped=3, failed=4, conflicts=5)
    assert counters.processed == 1 + 2 + 3 + 4
    assert RunStatus.RUNNING.is_active and RunStatus.QUEUED.is_active
    assert not RunStatus.SUCCEEDED.is_active
