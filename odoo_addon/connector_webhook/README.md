# FastAPI Connector Webhooks (Odoo addon)

Posts signed JSON events from Odoo to the FastAPI connector (`POST /webhooks/odoo`):

| Odoo change | Event |
| --- | --- |
| `res.partner` created | `partner.created` |
| `res.partner` written (`name`, `email`, `phone`, `vat`, `is_company`) | `partner.updated` |
| `sale.order` moves to state `sale` (confirmed) | `sale_order.confirmed` |

Target: Odoo 17.0+ (manifest version `17.0.1.0.0`). Depends on `base`, `sale`, `base_automation`.

## Install

1. Copy the `connector_webhook/` folder into a directory on your Odoo `addons_path`.
2. Restart Odoo, enable developer mode, then Apps > Update Apps List.
3. Search "FastAPI Connector Webhooks" in Apps and click Install. (CLI alternative:
   `odoo -d <db> -i connector_webhook --stop-after-init`.)
4. Set the system parameters below.

## Configuration (Settings > Technical > System Parameters)

| Key | Value |
| --- | --- |
| `connector_webhook.url` | Base URL of the connector, e.g. `https://connector.example.com` (no trailing path; the addon appends `/webhooks/odoo`). The install creates it with a placeholder you must replace. |
| `connector_webhook.secret` | The connector's `WEBHOOK_SECRET` (at least 16 characters). **Create this one yourself**: the addon ships no default secret. |

While either value is missing the addon logs a warning and sends nothing. Never log or share the secret;
the addon never writes it to the Odoo log.

## How it works

- The server actions call `env['connector.webhook']._send_event(event_type, record)`.
- The body is built once (`{"event_id", "event_type", "model", "record_id", "occurred_at", "payload"}`),
  serialised with `json.dumps(..., separators=(",", ":"))` and signed over exactly those bytes:
  `HMAC-SHA256(secret, f"{timestamp}." + body)` as lowercase hex, sent as `X-Odoo-Timestamp` and
  `X-Odoo-Signature: sha256=<hex>` (`models/signing.py`; it is tested against the connector's
  `verify`).
- The event is posted **after the transaction commits** (`env.cr.postcommit`), so rolled-back changes
  never emit events, and sending errors are logged, never raised, so they cannot break the user's
  save. The payload carries only a few safe fields (partner: `name`, `email`, `is_company`,
  `company_id`; sale order: `name`, `partner_id`, `amount_total`, `currency`, `state`, `company_id`).
- Retries: connection errors/timeouts and 5xx are retried up to 3 times (0.5 s, 1 s, 2 s backoff),
  reusing the same `event_id` with a fresh timestamp and signature per attempt. 401, 413, 422 and other
  4xx are never retried. Delivery is **at-least-once**: the connector deduplicates by `event_id`, but
  handlers there must still be idempotent. The post runs in the worker that saved the record, so a
  down connector can delay that request by a few seconds (5 s timeout per attempt).

## Verify

1. Create a partner in Odoo.
2. Odoo log: `connector webhook partner.created res.partner(<id>) event_id=... -> 202 after 1 attempt(s)`.
3. Connector log: `odoo event received` / `partner event` with the same record id.

A `401` means the secrets differ (or the clocks differ by more than `WEBHOOK_TOLERANCE_SECONDS`).

## Version caveats and manual alternative

I could not run this against a live Odoo here; the XML follows the documented `base.automation` model and
should be checked on your version.

- `base.automation.trigger` values `on_create` / `on_write` exist in 17+. Older versions
  (<= 16) use `on_create_or_write` plus different server-action wiring; `cr.postcommit` is 16+.
- `action_server_ids` is a Many2many in 17 and a One2many in 18+. The data file uses `(4, id)` commands,
  which work for both. If your version rejects a field, remove that automation from
  `data/base_automation.xml` and create it in the UI instead.
- `trigger_field_ids` limits `partner.updated` to the listed fields. If your version does not support
  it, writes to any partner field send an event (harmless: the connector just logs it).
- Odoo 19 may rename or move automation fields; check the module on a test database first.

Manual setup via the UI (Settings > Technical > Automation > Automation Rules), one rule per row:

| Model | Trigger | Before update domain | Apply on | Action |
| --- | --- | --- | --- | --- |
| Contact | On creation | | | Execute Python code (A) |
| Contact | On update (fields: Name, Email, Phone, Tax ID, Is a Company) | | | Execute Python code (B) |
| Sales Order | On update (field: Status) | `[('state', '!=', 'sale')]` | `[('state', '=', 'sale')]` | Execute Python code (C) |

Python code (replace the event name):

```python
for record in records:
    env["connector.webhook"]._send_event("partner.created", record)  # A
    # env['connector.webhook']._send_event('partner.updated', record) # B
    # env['connector.webhook']._send_event('sale_order.confirmed', record)  # C
```
