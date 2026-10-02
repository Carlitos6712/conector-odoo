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
- [ ] T3 Odoo client: transport port + jsonrpc (httpx, retries/backoff on network errors only) + xmlrpc (`asyncio.to_thread`), uid cache + re-auth, `execute_kw` + helpers, fault mapping, company context. respx tests. Route: delegated (writer).
- [ ] T4 Odoo repository adapters (customer, product, sale order) + json2 transport + transport factory. Route: delegated (writer).
- [ ] T5 API: routers, schemas, DI wiring, error handlers (401/404/422/502), `X-API-Key`, `/health`. TestClient tests. Route: delegated (writer).
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

## Next step
T3.
