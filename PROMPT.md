Build a bidirectional connector between a FastAPI app and Odoo, in this folder. Main focus: FastAPI -> Odoo. Secondary: Odoo -> FastAPI (webhooks).

## Stack
- Python 3.11+, FastAPI, Pydantic v2, pydantic-settings, httpx, pytest, pytest-asyncio, respx.
- Manage deps with uv (or pip + requirements.txt if uv is missing).

## Architecture (hexagonal / screaming)
src/conector_odoo/
- domain/: entities (Customer, Product, SaleOrder), ports (CustomerRepository, SaleOrderRepository, ProductRepository). No framework imports.
- application/: use cases (CreateCustomer, UpdateCustomer, GetCustomer, SearchCustomers, CreateSaleOrder, ConfirmSaleOrder, HandleOdooEvent).
- infrastructure/odoo/: Odoo adapter implementing the ports.
- infrastructure/api/: FastAPI routers, schemas, dependency wiring, error handlers.
- config.py: settings from env vars.

## Odoo client (core of the task)
- Transport must be configurable: `ODOO_PROTOCOL=jsonrpc|xmlrpc|json2`. Implement jsonrpc (/jsonrpc) and xmlrpc (/xmlrpc/2) first; json2 (/json/2, Odoo 19, Bearer API key) as a third adapter if time allows.
- Auth with API key (never password). Authenticate once, cache uid, re-authenticate on auth failure.
- Generic `execute_kw` wrapper plus helpers: search_read, read, create, write, unlink (soft: archive via active=False), search_count.
- Async: run blocking xmlrpc calls through `asyncio.to_thread`; jsonrpc via httpx.AsyncClient with shared client, timeouts, and retries with backoff on network errors only (never retry non-idempotent create blindly).
- Map Odoo faults to domain errors: OdooAuthError, OdooNotFound, OdooValidationError, OdooUnavailable. API layer converts them to 401/404/422/502.
- Support multi-company via optional `company_id` context.

## FastAPI -> Odoo endpoints (v1)
- POST/GET/PATCH /customers (res.partner), GET /customers?email=&name=&limit=&offset=
- GET /products (product.product), GET /products/{id}
- POST /sale-orders (sale.order with lines), POST /sale-orders/{id}/confirm, GET /sale-orders/{id}
- GET /health (checks Odoo reachability and auth)
- Optional `X-API-Key` header auth on the connector itself (env `CONNECTOR_API_KEY`).
- Idempotency: accept `Idempotency-Key` header on POSTs; store in a small SQLite table to avoid duplicate creates.

## Odoo -> FastAPI (bidirectional part)
- POST /webhooks/odoo: receives events (partner created/updated, sale order confirmed). Verify HMAC SHA256 signature in `X-Odoo-Signature` with env `WEBHOOK_SECRET`. Reject invalid with 401.
- Dispatch events to registered handlers (simple in-process event bus); log and ack fast, process in BackgroundTasks.
- Include in `odoo_addon/` a minimal Odoo module (manifest + automated action / server action example in Python) that POSTs signed events to the connector for res.partner and sale.order. Document how to install it.

## Quality
- Strict TDD: write failing test first, then implementation. Unit tests for use cases with fake repositories; adapter tests with respx mocking Odoo JSON-RPC; API tests with TestClient.
- Type hints everywhere, ruff + mypy clean.
- Structured logging, no secrets in logs.

## Deliverables
- .env.example (ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY, ODOO_PROTOCOL, CONNECTOR_API_KEY, WEBHOOK_SECRET)
- Dockerfile + docker-compose.yml (connector only; Odoo is external)
- README.md: setup, env vars, endpoint examples with curl, how to create the Odoo API key, how to install the addon, architecture diagram (mermaid).
- Conventional commits, one commit per work unit. No AI attribution in commits.

Start by exploring this folder, then propose a short task list, then implement task by task.
