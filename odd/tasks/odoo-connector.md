# Feature: odoo-connector

Locator: `odd/tasks/odoo-connector.md` (Engram mirror: `odd/odoo-connector/tasks`)

## Objective
Bidirectional connector between a FastAPI app and Odoo, per `PROMPT.md`.
Primary: FastAPI -> Odoo (REST endpoints backed by Odoo RPC). Secondary: Odoo -> FastAPI (signed webhooks).

## Problem / Why
Clients need a clean, typed REST API over Odoo (res.partner, product.product, sale.order) without speaking Odoo RPC,
and need to react to Odoo events. Hexagonal architecture keeps the domain independent of Odoo transport and FastAPI.

## Scope (authorized)
Everything in `PROMPT.md`: hexagonal package `src/conector_odoo/`, Odoo client (jsonrpc, xmlrpc, json2), API v1,
idempotency (SQLite), webhooks (HMAC + event bus), `odoo_addon/`, Docker, README, `.env.example`.

## Constraints
- Python 3.12 (>=3.11), uv, FastAPI, Pydantic v2, pydantic-settings, httpx, pytest, pytest-asyncio, respx.
- Strict TDD: RED -> GREEN -> REFACTOR. Source: user global config ("Strict TDD Mode: enabled") + PROMPT.md. Runner: `uv run pytest`.
- ruff + mypy (strict) clean. Structured logging, no secrets in logs.
- API key auth to Odoo (never password). Never blindly retry non-idempotent `create`.
- Conventional commits, one per work unit, no AI attribution.

## Delivery strategy
`ask-on-risk` (default). Forecast: ~3000+ authored lines total; local repo with no remote, so no PRs are created. Work-unit commits on branch `feat/odoo-connector`.

## Tasks
- [x] T1 Scaffold: pyproject (uv), ruff/mypy/pytest config, `config.py` (settings), `.gitignore`, `.env.example`, logging setup. Route: delegated (writer).
- [x] T2 Domain + application: entities, ports, domain errors, use cases (CreateCustomer, UpdateCustomer, GetCustomer, SearchCustomers, CreateSaleOrder, ConfirmSaleOrder, HandleOdooEvent) with fake-repo unit tests. Route: delegated (writer).
- [x] T3 Odoo client: transport port + jsonrpc (httpx, retries/backoff on network errors only) + xmlrpc (`asyncio.to_thread`), uid cache + re-auth, `execute_kw` + helpers, fault mapping, company context. respx tests. Route: delegated (writer).
- [x] T3a Review follow-ups (R3-001..R3-005). Route: delegated (writer).
- [x] T4 Odoo repository adapters (customer, product, sale order) + json2 transport + transport factory. Route: delegated (writer).
- [x] T4a Review follow-ups (T4 review). Route: delegated (writer).
- [x] T5 API: routers, schemas, DI wiring, error handlers (401/404/422/502), `X-API-Key`, `/health`. TestClient tests. Route: delegated (writer).
- [x] T5a Review follow-ups (T5 4-lens review). Route: delegated (writer).
- [x] T6 Idempotency: `Idempotency-Key` on POSTs, SQLite store. Route: delegated (writer).
- [x] T6a Review follow-ups (T6 4-lens review). Route: delegated (writer).
- [x] T7 Webhooks: `/webhooks/odoo`, HMAC SHA256 verification, in-process event bus, BackgroundTasks. Route: delegated (writer).
- [x] T7a Review follow-ups (T7 4-lens review). Route: delegated (writer).
- [x] T8 `odoo_addon/`: minimal module posting signed events for res.partner and sale.order. Route: delegated (writer).
- [x] T9 Dockerfile, docker-compose.yml, README (setup, env, curl, API key, addon install, mermaid). Route: delegated (writer).
- [x] T10 Odoo client batching: keyset `iter_search_read`, chunked `read_many`/`create_many`/`write_many`, `BatchPartiallyApplied`, concurrency semaphore + httpx limits, settings `odoo_max_concurrency`/`odoo_batch_size`. Route: delegated writer.
- [x] T11 Streaming NDJSON export for customers and products. Route: delegated writer.
- [ ] T12 Bulk customer upsert endpoint. Route: delegated writer.

## Acceptance criteria
- All PROMPT.md endpoints exist and are tested; `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` pass.
- One conventional commit per task.

## Checks (per task)
`uv run pytest -q` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy src`

## Progress / evidence
(updated per task: commit SHA, checks observed, review tier)

- T7a-T9 native review: high, granted, 4 lenses, approved and acknowledged (lineage review-653c38c024e2e4db). `.env.example` user-change review (lineage review-f7f0de65ed2a0acc) found a live-looking API key; user moved values to `.env` and restored the template; correction exceeded the frozen 3-line budget, lineage abandoned (operator_disposition).

### T1 (route: delegated writer; commit: see `git log` subject "chore: scaffold project with uv, settings and logging")
- RED: `uv run pytest -q` -> 2 collection errors (`ModuleNotFoundError: conector_odoo.logging`, config missing).
- GREEN: 11 passed (settings parsing, SecretStr masking, protocol Literal, empty-optional -> None, cache, JSON logs, redaction).
- Checks: pytest 11 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Review tier: not assessed (writer task; native review per orchestrator).

### T2 (route: delegated writer; commit: subject "feat(domain): add entities, ports and use cases"; T1 = 429c6b9)
- RED: `uv run pytest -q` -> 3 collection errors (modules `application.customers`, `application.sale_orders`, `application.event_bus`/`events` missing).
- GREEN: 40 passed (customer/sale-order use cases with in-memory fakes, event bus isolation, HandleOdooEvent).
- Checks: pytest 40 passed; ruff check clean; ruff format --check clean; mypy src clean.

### T3 (route: delegated writer; commit: subject "feat(odoo): add async odoo client with jsonrpc and xmlrpc transports"; T2 = 3ac89a8)
- RED: `uv run pytest -q` -> `ImportError`/collection errors for errors, retry, jsonrpc, xmlrpc, client modules (errors module tested RED first: collection error, then GREEN 24 passed).
- GREEN: 124 passed (error mapping, retry policy, respx JSON-RPC incl. auth failure, re-auth, MissingError, ValidationError, retry on search_read, no retry on create, timeout, company context; XML-RPC via fake ServerProxy; OdooClient uid cache/re-auth/helpers).
- Checks: pytest 124 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Design: transport owns session uid; client caches uid and decides when to re-authenticate (documented in `transport.py`), keeping json2 implementable behind the same Protocol.

### T3 review + T3a follow-ups (route: delegated writer)
- T3 native review: medium, granted, lens review-reliability, approved and acknowledged (lineage review-aa1cbe628d540660); advisory R3-001..R3-005 fixed in T3a. T1+T2 combined review stopped with lens_context_budget_exceeded (no authority created); not reviewed.
- T3 commit: 1b35f41.
- T3a RED: 16 failed / 122 passed (permission-vs-auth mapping, no replay on AccessError/403, xmlrpc HTTPException/ExpatError, MissingError class-name precedence, create result guard).
- T3a GREEN: 138 passed. Checks: pytest 138 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decision: new `OdooPermissionError(ConnectorError)` (HTTP 403), not an `OdooAuthError` subclass, so the client never replays it. AccessError, HTTP 403, XML-RPC fault 4 map to it; AccessDenied, SessionExpiredException, HTTP 401 stay `OdooAuthError`.

### T4 (route: delegated writer; commit: subject "feat(odoo): add json2 transport, transport factory and repository adapters"; T3a = 2694104)
- RED: `uv run pytest -q` -> 5 collection errors (`ModuleNotFoundError` for json2, factory, customer/product/sale_order repository modules).
- GREEN: 205 passed (json2 respx tests incl. positional->named translation, error mapping, retry policy; factory per protocol; repositories with a recording fake client).
- Checks: pytest 205 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Design: json2 `authenticate` = `res.users/search` on the login, returns the user id; unsupported methods raise `OdooUnavailable` before any request. Repositories: `OdooCustomerRepository`, `OdooProductRepository`, `OdooSaleOrderRepository` (each takes an `OdooClient`); country code<->id cached in memory; product price from `lst_price`.

### T3a+T4 native review and T4a follow-ups (route: delegated writer)
- T3a+T4 native review: medium, granted, lens review-reliability, approved and acknowledged (lineage review-bd56fe2f22a6f4cf); advisory findings fixed in T4a. T3a=2694104, T4=4e442b3.
- T4a RED: 7 failed json2 authenticate tests + 9 failed repository tests (email wildcard escaping, company on read-back, created-id in read-back error, fake read recording company_id); client-over-json2 tests passed immediately (translation already correct, no fix needed).
- T4a GREEN: 229 passed. Checks: pytest 229 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decisions: email `=ilike` value escaped (`\`, `%`, `_`); name `ilike` left raw because Odoo escapes `ilike` itself (escaping would double-escape). Read-back after create uses the order company and, on failure, raises `OdooUnavailable("... <id> was created but could not be read back")`. json2 `authenticate` = `res.users/context_get` (key owner `uid`) compared with `res.users/search` on the login; mismatch -> `OdooAuthError`; missing `uid` in the context (undocumented for Odoo 19) logs a warning and falls back to the login lookup.

### T5 (route: delegated writer; commit: subject "feat(api): add fastapi routers, schemas, error handlers and api key auth"; T4a = d348f46)
- RED: product use-case tests -> collection error (`application.products` missing); `tests/api` -> collection error (`conector_odoo.infrastructure.api` missing).
- GREEN: 305 passed (product use cases, every endpoint happy path, 401/403/404/422/502 mappings, X-API-Key enforced/disabled, health ok/degraded, request id + request log, lifespan closes the client).
- Checks: pytest 305 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Design: `create_app(settings=None)` factory (`uvicorn conector_odoo.main:create_app --factory`); lifespan builds a `Container` (client + repositories) on `app.state.container`; repository dependencies are the test override points; `/health` public, all other routers declare `require_api_key`; email validated with a simple regex (no `email-validator` dependency). T6 hook: add the Idempotency-Key dependency beside `require_api_key` on the POST routes; T7 mounts its router in `_include_routers` without `require_api_key`.

### T4a+T5 native review and T5a follow-ups (route: delegated writer)
- T4a+T5 native review: high, granted, 4 lenses (risk, resilience, readability, reliability), approved and acknowledged (lineage review-60f09bb3a0f0ae05); advisory findings fixed in T5a; R1-001 kept optional per brief + startup warning. T4a=d348f46, T5=c016601.
- T5a RED: 4 collection errors (`CreatedButUnreadable`, `GetSaleOrder` missing, new test module) + 14 failures (secret min length, json2 context_get fallback, company_id query param).
- T5a GREEN: 331 passed. Checks: pytest 331 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decisions: `connector_api_key`/`webhook_secret` need >=16 chars (`hide_input_in_errors` so a rejected secret is not echoed); startup WARNING in the lifespan when the API key is unset. New `CreatedButUnreadable(model, record_id)` mapped to 202 `{error: created_but_unreadable, detail, id, model}` + `Location` (/customers/{id}, /sale-orders/{id}), built by one `read_back` helper shared by both repositories. json2 `context_get` non-auth failures warn and fall back to the login lookup (401 still raises). `scrub` ignores secrets <8 chars. Failure log line carries scrubbed `detail` and `request_id` (middleware sets `request.state.request_id`). `MAX_PAGE_SIZE` moved to `application/pagination.py`. `GetSaleOrder` use case; `company_id` query param on GET /sale-orders/{id} and POST /sale-orders/{id}/confirm (ports, fakes, adapter).

### T6 (route: delegated writer; commit: subject "feat(api): add sqlite-backed idempotency keys for post endpoints"; T5a = d36340a)
- RED: `uv run pytest -q tests/idempotency tests/api/test_idempotency_api.py` -> collection error (`ModuleNotFoundError: conector_odoo.infrastructure.idempotency`); after the first implementation pass, the in-progress test exposed a hash-vs-409 ordering mismatch in the test itself (fixed: the test now claims the key with the real request hash).
- GREEN: 354 passed. Checks: pytest 354 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Design: `IdempotencyStore` Protocol in `infrastructure/idempotency/store.py`; `SqliteIdempotencyStore` (one connection + `threading.Lock`, calls via `asyncio.to_thread`, `:memory:` supported, extra `response_headers` column so a replayed 202 keeps its `Location`). `IdempotencyGuard` dependency (`infrastructure/api/idempotency.py`, `GuardDep`) wraps the POST handlers via `guard.run(body, action, status)`; no middleware. Failure (any exception) releases the key; 2xx and 202 created_but_unreadable are stored; cancellation keeps the key in progress (the write may have happened). Hash = sha256 of canonical JSON of body + path params + query params; hash mismatch is checked before the in-progress check. Container gains `idempotency`, closed in the lifespan; default path `./data/idempotency.sqlite3` (parent dir created). `purge_older_than(hours)` available, no scheduler.

### T5a+T6 native review and T6a follow-ups (route: delegated writer)
- T5a+T6 native review: high, granted, 4 lenses, approved and acknowledged (lineage review-ace08c5627d82149); advisory findings fixed in T6a. T5a=d36340a, T6=1ff2bba.
- T6a RED: 18 failed (+1 collection error for the new `purge` module): unknown status/mark_unknown, stale `in_progress` -> unknown, file modes, settings (`odoo_api_key` min length, new idempotency settings), 503 on store failure, purge task + shutdown ordering, 202 log message, short-secret scrubbing. Cancellation and complete-failure tests were characterization tests (already green).
- T6a GREEN: 380 passed. Checks: pytest 380 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decisions: failures where the write may have happened (`OdooUnavailable`/any `ConnectorError` not in the no-write list, unexpected exceptions) mark the key `unknown` and store the error response; retry -> 409 `idempotency_outcome_unknown`. Only validation/not-found/auth/permission errors release the key. Abandoned `in_progress` rows (older than `idempotency_in_progress_timeout_seconds`) become `unknown` on `begin`. `scrub` masks every non-empty secret; `odoo_api_key` >= 16 chars. DB file 0600 (existing file tightened), new parent dir 0700. Lifespan purge task (`app.state.purge_task`) and per-resource try/finally on shutdown. Existing DBs created before this change keep the old CHECK constraint (no `unknown` status): delete the dev file (unreleased schema).

### T7 (route: delegated writer; commit: subject "feat(webhooks): receive signed odoo events and dispatch to event bus"; T6a = 28cee70)
- RED: `uv run pytest -q` -> 4 collection errors (`ModuleNotFoundError` for `infrastructure.webhooks.{signature,store,handlers}` and the webhooks API tests importing them).
- GREEN: 438 passed (HMAC sign/verify vectors, boundary/malformed inputs, SQLite dedup store, default handlers, endpoint: valid/bare-hex/bad/missing/stale/tampered signature, duplicate, replay, invalid payload, unknown type, 413 incl. chunked, no API key needed, handler isolation, 503 on store failure). Checks: pytest 438 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Design: scheme `HMAC-SHA256(secret, f"{ts}.".encode() + raw_body)` hex, headers `X-Odoo-Timestamp` + `X-Odoo-Signature: sha256=<hex>` (documented in `routers/webhooks.py` and `infrastructure/webhooks/signature.py`). Dedup in table `webhook_events` of the idempotency SQLite file (own connection; purged by the lifespan loop via `MultiPurger`). Unknown `event_type` -> 202 `ignored` (logged, not dispatched). Event id recorded only after signature + schema validation. `Container` gains `event_bus` + `webhook_events`; `EventBus` port gains `subscribe`. Body read by streaming with a 1 MiB cap.

### T6a+T7 native review and T7a follow-ups (route: delegated writer)
- T6a+T7 native review: high, granted, 4 lenses, approved and acknowledged (lineage review-04ca3fec3f189390); advisory findings fixed in T7a. T6a=28cee70, T7=923d216.
- T7a RED: 26 failed + 1 collection error (`infrastructure.sqlite` missing): 5000-digit timestamp raised, `claim`/`status`/`mark_processed` missing, bus returned None, naive/unparsable `created_at`, `clock` seam, new setting, generic purge log. MultiPurger isolation test was a characterization test (already green).
- T7a GREEN: 467 passed. Checks: pytest 467 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decisions: `verify` rejects timestamps over 12 digits before `int()`. Webhook dedup is two-phase (`received` -> `processed`; `claim` returns new/redeliver/duplicate; `webhook_redelivery_after_seconds`, default 60); the bus `publish` and `HandleOdooEvent.execute` now return `bool` (all handlers succeeded) so the background task marks `processed` only on full success; delivery is at-least-once, handlers must be idempotent. Existing `webhook_events` tables are migrated (`status` column, legacy rows = processed). Naive `created_at` = UTC, unparsable = abandoned (`unknown`, warning log). Stores take an injectable `clock`. Shared SQLite boilerplate in `infrastructure/sqlite.py` (`SqliteDatabase`, `prepare_private_file`). `DEFAULT_IN_PROGRESS_TIMEOUT_SECONDS` lives in `idempotency/store.py` and is imported by config and the store. Purge logs: "purged expired records" / "purge failed" with a `store` field.

### T8 (route: delegated writer; commit: subject "feat(addon): add odoo module that posts signed events to the connector"; T7a = fc20dd0)
- RED: `uv run pytest -q tests/addon` -> collection error (`FileNotFoundError: odoo_addon/connector_webhook/models/signing.py`); a test expecting a non-ASCII-escaped body then failed against the spec'd `json.dumps` defaults (test corrected, spec followed).
- GREEN: 488 passed (signing verifies with the connector's `verify`, header contract, event shape, retry matrix incl. fresh timestamp per attempt and same bytes, no retry on 4xx, secret never logged, manifest via `ast.literal_eval`, XML well-formed, server-action code is valid Python, config parameter data has no secret and is `noupdate`). Checks: pytest 488 passed; ruff check clean; ruff format --check clean; mypy src clean (addon outside `src`).
- Design: all pure logic (body, signing, retrying `deliver`) in `models/signing.py` (no `odoo` import); `models/connector_webhook.py` is a thin AbstractModel `connector.webhook` that reads `ir.config_parameter`, builds the payload and posts via `env.cr.postcommit.add`. Ruff: `known-third-party = ["odoo"]` and per-file ignores for `__init__.py` (F401) and `__manifest__.py` (B018). Retries: 3 retries (4 attempts) on transport errors and 5xx, 0.5/1/2 s backoff, same event_id, fresh timestamp+signature.
- Odoo-version uncertainty: addon not run against a live Odoo. `base.automation` XML uses `trigger` `on_create`/`on_write`, `(4, id)` links (works for the Many2many of 17 and the One2many of 18+), `trigger_field_ids`, `filter_pre_domain`/`filter_domain`, `ir.actions.server` `usage=base_automation`; Odoo 19 field names unverified. Manual UI alternative documented in the addon README.

### T9 (route: delegated writer; commit: subject "docs: add dockerfile, compose and readme"; T8 = d3aa7fd)
- Non-Python unit: no RED/GREEN cycle (configuration and documentation). Checks: pytest 488 passed; ruff check clean; ruff format --check clean; mypy src clean.
- `docker build -t conector-odoo:dev .` succeeded (multi-stage, uv `sync --frozen --no-dev`, non-root uid 10001). Smoke run: container started, `/health` answered 503 `degraded` ("cannot reach Odoo") against an unreachable Odoo as designed, `/app/data` owned by the app user.
- README env table checked against `config.py` (all 17 variables and defaults match). The openssl signing example was compared with the Python HMAC for the same input (identical digest).

### T10 (route: delegated writer; commit: subject "feat(odoo): add keyset batch iteration, chunked operations and concurrency limit")
- RED: `uv run pytest -q` -> 2 collection errors (`ImportError: BatchPartiallyApplied` from `conector_odoo.domain.errors` in the new batching tests and the API error-mapping test).
- GREEN: 532 passed (keyset domain progression over 3 batches, empty result, full last batch costs one extra call, batch size validation, chunk boundaries 0/1/100/101/250, order preservation and missing ids in `read_many`, partial failure carries created ids and chunk index, semaphore caps in-flight calls with an `asyncio.Event`-gated fake transport, no deadlock with one slot on re-auth, json2 multi-create body, settings bounds, factory passes limits, 502 `batch_partially_applied` body). Checks: pytest 532 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decisions: first batch has no `id` clause, later ones append `["id", ">", last_id]`; the semaphore wraps each transport call (and `authenticate`) but is never held across a re-authentication. A failure of the first `create_many` chunk re-raises the original error (nothing applied); `BatchPartiallyApplied` is only raised when earlier chunks created records. Malformed multi-create results (wrong length or non-int ids) raise `OdooUnavailable`. Pool limits apply to jsonrpc/json2 only (xmlrpc has no pool; its calls are still capped by the semaphore). Batching constants live in `application/pagination.py`.

### T11 (route: delegated writer; commit: subject "feat(api): stream customers and products as ndjson exports"; T10 = 384d084)
- RED: `uv run pytest -q` -> 6 then 8 collection errors (`ImportError: CustomerFilter`, then `TypeError: 'function' object is not subscriptable` from the new `list` method shadowing the builtin in the `ProductRepository` class body; fixed by declaring `iter_batches` before `list`).
- GREEN: 570 passed (use cases: batches in order, filters/batch size passed down, eager batch-size validation, errors propagate; adapters: keyset domain with filters and escaped email, configured default batch size, country lookup once per batch with no N+1, mid-stream error; API: multi-batch NDJSON in order with exact shape, filters passed down, empty export, `/customers/export` not captured by `/{customer_id}`, batch_size 422 for 0/-1/5001/abc and bounds 1/5000 accepted, api key enforced on both routes, error before first byte maps to 403, mid-stream failure appends a scrubbed error line and is logged, unexpected failure hides details, lazy one-batch-at-a-time pulling and source closed). Checks: pytest 570 passed; ruff check clean; ruff format --check clean; mypy src clean.
- Decisions: use cases return `AsyncIterator[list[Entity]]` (batches), not a flat entity iterator, so the router writes one chunk per batch instead of one ASGI send per row. The router fetches the first batch before building the `StreamingResponse` so early failures use the normal handlers; later failures end the stream with `{"error", "detail"}`. Extra optional `active` filter on customers (`CustomerFilter.active`; explicit value also matches archived partners). `/export` routes are declared before `/{id}`. Repositories take `batch_size` from `ODOO_BATCH_SIZE`.

### Pending for user
- `.env.example` should also list `ODOO_MAX_CONCURRENCY` (default 8), `ODOO_BATCH_SIZE` (default 500) and `BULK_MAX_ITEMS` (default 1000).
- `.env.example` needs updating (new settings: `IDEMPOTENCY_IN_PROGRESS_TIMEOUT_SECONDS`, `IDEMPOTENCY_TTL_HOURS`, `IDEMPOTENCY_PURGE_INTERVAL_SECONDS`, `WEBHOOK_TOLERANCE_SECONDS`, `WEBHOOK_REDELIVERY_AFTER_SECONDS`; 16-character minimum for `ODOO_API_KEY`, `CONNECTOR_API_KEY`, `WEBHOOK_SECRET`). Subagents have no access to `.env*` files.

## Next step
Final review of T7a-T9, user updates `.env.example`, then the delivery decision (push/PR) by the user.
