import logging

import requests
from odoo import api, models

from . import signing

_logger = logging.getLogger(__name__)

PARAM_URL = "connector_webhook.url"
PARAM_SECRET = "connector_webhook.secret"
ENDPOINT_PATH = "/webhooks/odoo"


class ConnectorWebhook(models.AbstractModel):
    """Builds, signs and posts events to the FastAPI connector.

    Configure it in Settings > Technical > System Parameters:

    * ``connector_webhook.url``: base URL of the connector, e.g. ``https://connector.example.com``
    * ``connector_webhook.secret``: the connector's ``WEBHOOK_SECRET`` (at least 16 characters)

    Sending never breaks the user's transaction: the event is posted after the commit and every
    error is logged, never raised.
    """

    _name = "connector.webhook"
    _description = "FastAPI connector webhook sender"

    @api.model
    def _send_event(self, event_type, record):
        """Queue ``event_type`` for ``record``; it is posted only if the transaction commits."""
        try:
            params = self.env["ir.config_parameter"].sudo()
            base_url = (params.get_param(PARAM_URL) or "").strip().rstrip("/")
            secret = params.get_param(PARAM_SECRET) or ""
            if not base_url or not secret:
                _logger.warning(
                    "connector webhook not configured (set %s and %s); %s skipped",
                    PARAM_URL,
                    PARAM_SECRET,
                    event_type,
                )
                return
            event = signing.build_event(
                event_type, record._name, record.id, self._event_payload(record)
            )
            body = signing.serialize_body(event)
            url = base_url + ENDPOINT_PATH
            event_id = event["event_id"]
            model_name, record_id = record._name, record.id
        except Exception:
            _logger.exception("could not build connector webhook event %s", event_type)
            return

        def _post_after_commit():
            self._post(url, secret, body, event_type, model_name, record_id, event_id)

        self.env.cr.postcommit.add(_post_after_commit)

    @api.model
    def _event_payload(self, record):
        """Small, safe field subset per model (never relations' contents, never secrets)."""
        if record._name == "res.partner":
            return {
                "name": record.name or None,
                "email": record.email or None,
                "is_company": bool(record.is_company),
                "company_id": record.company_id.id or None,
            }
        if record._name == "sale.order":
            return {
                "name": record.name,
                "partner_id": record.partner_id.id or None,
                "amount_total": record.amount_total,
                "currency": record.currency_id.name or None,
                "state": record.state,
                "company_id": record.company_id.id or None,
            }
        return {}

    @staticmethod
    def _post(url, secret, body, event_type, model_name, record_id, event_id):
        """Runs after commit, outside any cursor; must never raise."""
        try:
            result = signing.deliver(requests.post, url, secret, body)
        except Exception:
            _logger.exception("connector webhook %s crashed", event_type)
            return
        log = _logger.info if result.ok else _logger.error
        log(
            "connector webhook %s %s(%s) event_id=%s -> %s after %s attempt(s)",
            event_type,
            model_name,
            record_id,
            event_id,
            result.status_code if result.status_code is not None else "no response",
            result.attempts,
        )
