"""Webhook trigger: runs sync jobs when a verified Odoo event arrives.

The HTTP intake (``POST /webhooks/odoo``) is untouched: it verifies the HMAC signature, applies
the replay window, deduplicates the event id and publishes the event on the in-process bus.
``HandleWebhookTrigger`` is just another bus handler, so nothing reaches a job that did not pass
those checks.

A job listens to an event when it is enabled, has a ``WebhookTrigger`` and the event type is one of
its ``event_types``. If the event's model equals the job's source resource and the job reads side A
(``A_TO_B`` / ``BIDIRECTIONAL``), only that record is synced (``only_records``); otherwise the job
runs in full (idempotent thanks to the xref hashes). A busy job is skipped; one job failing never
stops the others, but the failures are re-raised together so the bus reports the delivery as
incomplete and Odoo's redelivery retries it (at-least-once; reruns are idempotent).
"""

import logging

from conector_odoo.application.sync_trigger import TriggerOutcome, TriggerSyncJob
from conector_odoo.domain.events import KNOWN_EVENT_TYPES, OdooEvent
from conector_odoo.domain.ports import EventBus, SyncJobRepository
from conector_odoo.domain.sync import Direction, SyncJob, TriggerKind, WebhookTrigger

logger = logging.getLogger(__name__)


class HandleWebhookTrigger:
    def __init__(self, jobs: SyncJobRepository, trigger: TriggerSyncJob) -> None:
        self._jobs = jobs
        self._trigger = trigger

    async def __call__(self, event: OdooEvent) -> None:
        failures: list[Exception] = []
        for job in await self._jobs.list():
            if job.id is None or not self._listens(job, event):
                continue
            try:
                result = await self._trigger.execute(
                    job.id, TriggerKind.WEBHOOK, only_records=self._only_records(job, event)
                )
            except Exception as exc:
                logger.exception("webhook-triggered sync crashed", extra={"job_id": job.id})
                failures.append(exc)
                continue
            if result.outcome is not TriggerOutcome.COMPLETED:
                logger.info(
                    "webhook trigger skipped",
                    extra={"job_id": job.id, "outcome": result.outcome.value},
                )
        if failures:
            raise ExceptionGroup("webhook-triggered sync jobs failed", failures)

    @staticmethod
    def _listens(job: SyncJob, event: OdooEvent) -> bool:
        return (
            job.enabled
            and isinstance(job.trigger, WebhookTrigger)
            and event.event_type in job.trigger.event_types
        )

    @staticmethod
    def _only_records(job: SyncJob, event: OdooEvent) -> list[str] | None:
        if job.direction is not Direction.B_TO_A and job.source.resource == event.model:
            return [str(event.record_id)]
        return None


def register_webhook_triggers(bus: EventBus, handler: HandleWebhookTrigger) -> None:
    """Subscribe the trigger handler to every event type the intake can publish."""
    for event_type in sorted(KNOWN_EVENT_TYPES):
        bus.subscribe(event_type, handler)
