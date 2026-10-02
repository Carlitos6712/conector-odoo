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
- [ ] T6 Idempotency: `Idempotency-Key` on POSTs, SQLite store. Route: delegated (writer).
- [ ] T7 Webhooks: `/webhooks/odoo`, HMAC SHA256 verification, in-process event bus, BackgroundTasks. Route: delegated (writer).
- [ ] T8 `odoo_addon/`: minimal module posting signed events for res.partner and sale.order. Route: delegated (writer).
- [ ] T9 Dockerfile, docker-compose.yml, README (setup, env, curl, API key, addon install, mermaid). Route: delegated (writer).

## Acceptance criteria
- All PROMPT.md endpoints exist and are tested; `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` pass.
- One conventional commit per task.

## Checks (per task)
`uv run pytest -q` · `uv run ruff check .` · `uv run ruff format --check .` · `uv run mypy src`

## Progress / evidence
(updated per task: commit SHA, checks observed, review tier)

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

## Next step
T6.
