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
- [ ] BE1 Settings persistence + migration 7 + ActiveOdooConnection service + provider swap (tests: concurrent swap, failed probe keeps old, close-after-inflight, startup matrix profile/env/none/broken)
- [ ] BE2 Admin routes + `is_active`/`last_connected_at` in profile responses + delete refusal + role tests + legacy routers 503 + health
- [ ] BE3 docker-compose + README + docs/architecture + tracker
- [ ] FE (next writer) Settings/Connection screen: show active connection, activate/disconnect, badges on the profile list, "not configured" banner

## Route log
- Tracker created before the first source write. BE1-BE3: single writer (this agent, delegated by the parent orchestrator), direct work.

## Commits
(filled as they land)

## Progress / verification
Baseline: 1822 passed (stated by the parent).
