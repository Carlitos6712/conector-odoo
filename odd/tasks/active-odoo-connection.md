# Feature: active-odoo-connection

## Objective
Enter the Odoo connection parameters in the admin frontend (Odoo connection profiles) instead of `.env`. The app remembers the LAST CONNECTED Odoo across restarts and can switch to another one at any time without a restart.

## Problem
`ODOO_URL/DB/USER/API_KEY` were REQUIRED env vars that built ONE fixed `OdooClient` at startup for the legacy data API (`/customers`, `/products`, `/sale-orders`) and `/health`. The webhook intake never used it (handlers only log).

## Constraints
- Hexagonal: domain stays framework-free; ports in `domain/ports.py`, use cases in `application/`, adapters in `infrastructure/`.
- English code, comments, docs. Conventional Commits, no AI attribution. Work-unit commits per task, tests and docs alongside.
- `WEBHOOK_SECRET` and `CONNECTOR_API_KEY` stay in env. External REST API values already come from profiles.
- `.env.example` has an uncommitted user edit: never touched, never `git add -A`; stage by explicit path only.
- No push. Do not touch external containers (SUWE fake :8000, Odoo dev :8069).

## Authorized scope
Backend (BE1-BE3) on branch `feat/active-odoo-connection` (from main). The frontend (FE) is a separate writer.

## TDD
Mode: enabled (project config, Strict TDD). Runner: `uv run pytest`.

## Design
- Migration 7 `app_settings(key, value, updated_at)`; keys `odoo.active_profile_id`, `odoo.last_connected_at`, `odoo.last_connected_profile_id`, `odoo.profile.<id>.last_connected_at`.
- `ActiveOdooConnection` (application) orchestrates: build candidate client -> probe -> persist -> atomic swap in `OdooConnectionProvider` (infrastructure) -> old client closed after its in-flight leases end.
- Startup resolution: active profile (exists + decrypts + builds) > env (all four ODOO_* set, source `env`) > none. Never crashes startup.
- Legacy routers take a lease per request through the provider; source `none` -> 503 `odoo_not_configured`.
- Admin: `GET/PUT/DELETE /admin/api/odoo/active`; profile list exposes `is_active` and `last_connected_at`; deleting the active profile is refused (409).

## Tasks
- [x] BE1 Settings persistence + migration 7 + ActiveOdooConnection service + provider swap (tests: concurrent swap, failed probe keeps old, close-after-inflight, startup matrix profile/env/none/broken)
- [x] BE2 Admin routes + `is_active`/`last_connected_at` in profile responses + delete refusal + role tests + legacy routers 503 + health
- [x] BE3 docker-compose + README + docs/architecture + tracker
- [x] FE1 Data layer: typed API, `useActiveOdoo` (30 s refetch, paused when hidden), activate/disconnect mutations invalidating `["odoo","active"]`, profiles and dashboard, error mapping (`odoo_activation_failed` carries the probe steps)
- [x] FE2 Connections: active panel (profile/env/none/fallback, disconnect), `Activa` badge, last-connection column, confirmed "Usar como conexión activa" with probe progress and failing step, delete-active 409 message, live region
- [x] FE3 Wizard "Guardar y activar" (failed activation keeps the saved profile, retry without re-creating) and dashboard "Odoo activo" card + attention items (none/fallback)
- [x] FE4 e2e step (activate the fake Odoo, `Activa` badge, env banner before) + README usage

## Route log
- Tracker created before the first source write. BE1-BE3: single writer (this agent, delegated by the parent orchestrator), direct work.
- FE1-FE4: single writer (delegated by the parent orchestrator), delegated direct; one non-trivial multi-file write, no SDD artifacts.

## Commits
- BE1: 3c97e30 feat(odoo): resolve the Odoo connection at runtime and swap it without a restart
- BE2: 44a40a4 feat(admin): expose the active Odoo connection and switch it from the admin API
- BE3: 9a7f0d2 docs(odoo): make ODOO_* optional and document the active Odoo connection
- FE1: 9c43505 feat(frontend): add the active Odoo connection data layer
- FE2: 3fb0b5d feat(frontend): show and switch the active Odoo connection from Connections
- FE3: 02c37b8 feat(frontend): save and activate an Odoo connection and surface it on the dashboard
- FE4 + tracker: see `git log --grep 'docs(odd)'`

## Progress / verification
Baseline: 1822 passed (observed at start).
BE1: RED observed (collection ModuleNotFoundError `application.active_odoo`; later `container.odoo` missing for the 503 tests). The streaming-lease test (`test_swap_during_streaming.py`) had no separate RED: it characterises the wiring written just before; it fails if the lease is released when the endpoint returns (verified by reasoning, not by mutation). Decisions: provider = `OdooConnectionProvider` (acquire/release leases, `commit` swaps in one synchronous step, retired client closed on its last release or at once when idle, `aclose` force-closes at shutdown and re-raises the first close error after closing all); the legacy repos are built per connection; `Container.odoo_client` stays as a property so older tests keep working; env connection stays outside the outbound policy, profile connections are inside it; probe uses the existing `OdooConnectionProbe` (always JSON-RPC) and runs BEFORE persisting and swapping; startup never probes. Webhook handlers never used the Odoo client (they only log), so nothing changed there.
BE2: RED observed (14 failed on the missing route/fields). Edits to the active profile reload the live client without probing (`refresh_if_active`); `is_active` reflects the PERSISTED active id (a startup fallback shows in `GET /odoo/active` as status `fallback` + warning, not in the profile list).
BE3: `docker compose config` with only the required vars renders (ODOO_* as empty strings, treated as unset by `env_ignore_empty`). No `docker compose up` run.
Final: `uv run pytest` 1897 passed (baseline 1822, +75 new, no existing test edited); ruff check, ruff format --check, mypy src clean; e2e `npx playwright test` 3 passed (e2e backend still passes ODOO_* = legacy mode). Live check with `tests/e2e_support/fake_odoo.py` on a private port: app started with no ODOO env -> /health `not_configured`, /customers 503; created and activated a profile -> /health reachable, /customers 200; restarted without any ODOO env -> still reachable (persisted). The external Odoo dev (:8069) and SUWE fake were not written to.
Not done (BE):  protocol per profile (profiles have no protocol field, the global ODOO_PROTOCOL applies); `.env.example` (user edit pending, see report).

FE: baseline 572 vitest. Strict TDD, RED observed for every suite (data layer 12 failed; Connections UI 17 failed; wizard 5 failed; dashboard 5 failed + 2 for `odooAttention`; `formatRelativeTime` failed on the missing module). Cases that passed on first run because they characterise existing behaviour (no RED): REST rows show no last-connection data, REST wizard has no "Guardar y activar", plain "Guardar conexión" does not activate, healthy Odoo raises no attention item. Final: `npm run lint`, `typecheck`, `build` clean; `npm test` 625 passed (57 files); `npx playwright test` 3 passed (new step activates the fake Odoo and asserts the `Activa` badge and the env banner switching away; needs `npm run build` in frontend first because the backend serves `frontend/dist`).
Decisions: "Cambiar" focuses the profile list heading (no select dialog); "Desconectar" only for source `profile` (an env connection has nothing stored to forget); the raw server `warning` is never rendered (fixed translated text instead); the activate dialog says the data API and health use the new Odoo and omits webhooks because the webhook handlers never touch the Odoo client; the delete-active 409 is distinguished from "in use" by the row's `is_active` (both are 409 `conflict`).
Not done (FE): switching the active connection from the dashboard; no e2e for the failing-activation path (unit-covered).
