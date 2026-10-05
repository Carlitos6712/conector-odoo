# Architecture

Hexagonal: the domain and the application layer know only ports; adapters implement them.
Back to the [README](../README.md).

## Component view

```mermaid
flowchart LR
    spa["React SPA<br/>(frontend/)"]
    admin["Admin API<br/>/admin/api"]
    data["Data API<br/>X-API-Key"]
    hook["Webhook intake<br/>/webhooks/odoo (HMAC)"]
    sched["Scheduler<br/>(in-process cron)"]
    app["Application<br/>sync runner, mappings,<br/>jobs, profiles"]
    ports{{"Ports<br/>RecordSource / RecordSink"}}
    rest["REST adapter"]
    odoo["Odoo adapter"]
    admindb[("admin.db<br/>SQLite")]
    idemdb[("idempotency.sqlite3")]
    ext["External REST API"]
    odooapp["Odoo"]

    spa --> admin --> app
    sched --> app
    hook -- "event bus" --> app
    data --> app
    app --> ports
    rest -. implements .-> ports
    odoo -. implements .-> ports
    rest --> ext
    odoo --> odooapp
    app --> admindb
    data --- idemdb
    hook --- idemdb
```

Reading guide:

- Entry points (left) never talk to adapters directly; they call application use cases.
- `RecordSource` (`describe`, `iter_batches`, `get`, `sample`) and `RecordSink` (`describe`,
  `find_by`, `create`, `update`) are `Protocol`s in `domain/ports.py`. `RecordEndpoint` is both.
  Every Odoo model and every REST resource is just another endpoint, so the sync runner is generic.
- The runner gets endpoints from `ProfileEndpoints` (`infrastructure/endpoints.py`), which builds
  them from a stored connection profile and decrypts its secrets with the vault.
- The data API (customers, products, sale orders) is the original, Odoo-only part of the service. It
  keeps its own repositories and the idempotency store; see [data-api.md](data-api.md).

## One sync run

```mermaid
sequenceDiagram
    autonumber
    participant T as Trigger (manual, cron, webhook)
    participant R as Sync runner
    participant S as Source endpoint
    participant M as Mapping engine
    participant X as xref table
    participant K as Sink endpoint
    T->>R: start run (job, options)
    loop each batch of the source
        R->>S: iter_batches (batch_size, filter)
        S-->>R: records
        R->>M: apply mapping (record)
        M-->>R: fields (or rule errors: this record fails)
        R->>X: look up pair, compare content hash
        alt hash unchanged
            R->>R: skip
        else new record
            R->>K: find_by(upsert key) or create(idempotency key)
        else known pair
            R->>K: update
        end
        R->>X: save pair and hash
        R->>R: save counters, checkpoint, heartbeat
    end
    R-->>T: run status (succeeded, partial, failed, cancelled)
```

Rules the runner follows (full algorithm in the docstring of `application/sync_runner.py`):

| Concern | Behaviour |
| --- | --- |
| Idempotency | A create carries the key `sync:{job_id}:{source_id}:{content_hash}`; a record whose hash equals the stored one is skipped, so re-running an unchanged job writes nothing. |
| Adoption | With an upsert key `field:<name>`, an existing destination record that matches is adopted (updated, xref written) instead of duplicated. |
| Errors | A bad record (mapping error, remote rejection) is stored in `run_errors` with a redacted payload and a retryable flag; the run continues. An auth error, a missing resource or too many errors fails the whole run. |
| Resume | After every batch the counters, checkpoint and heartbeat are saved. A failed, cancelled or stale (no heartbeat for 15 minutes) run can be resumed; failed records can be retried. |
| Bidirectional | Forward pass A to B, then reverse pass B to A. Two hashes per pair prevent echo; a change on both sides is resolved by the conflict rule (`source_wins`, `target_wins`, `newest_wins`, `flag_conflict`). |
| Dry run | Reads only: no destination writes, no xref writes; counters mean would-create / would-update / would-skip. |

## Module map

| Layer | Path | Holds |
| --- | --- | --- |
| Domain | `src/conector_odoo/domain/` | Records, ports, mapping model and engine, cron evaluator, sync job and run model, errors. No framework imports. |
| Application | `src/conector_odoo/application/` | Use cases: sync runner, run launcher, scheduler, webhook triggers, mappings, jobs, profiles, auth, dashboard, plus the legacy customer, product and sale-order use cases. |
| REST adapter | `infrastructure/rest/` | Pagination, auth (API key, bearer, OAuth2 client credentials, OIDC), retries, error normalisation. |
| Odoo adapters | `infrastructure/odoo/` | Client with three transports; `records.py` is the model-generic endpoint, the other repositories serve the data API. |
| Persistence | `infrastructure/{profiles,resources,mappings,sync,auth,migrations}/` | SQLite repositories, the secret vault and the versioned migrator. |
| Admin API | `infrastructure/admin_api/` | `/admin/api` routers, sessions, CSRF, roles. |
| Static UI | `infrastructure/api/static_frontend.py` | Serves `frontend/dist` with an SPA fallback. |
