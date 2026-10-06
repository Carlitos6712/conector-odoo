# admin-auth-disabled

## Objective
Let the admin UI/API run without login for a local, company-internal deployment, behind an explicit
flag. Secure behavior stays the default.

## Why
Login failed on the local setup (bootstrap only runs on an empty users table; Secure cookie). The app
is local and used by company members only, so the user chose to skip authentication.

## Scope / constraints
- Flag `ADMIN_AUTH_DISABLED` (default `false`). When `true`, `current_session`
  (`src/conector_odoo/infrastructure/admin_api/deps.py`) returns a synthetic admin session and CSRF
  passes. `CONNECTOR_API_KEY` and the webhook HMAC are NOT touched.
- Launcher enables the flag and binds the backend to `127.0.0.1` (no LAN exposure without login).
- Frontend: hide/redirect the login screen when `/me` already returns a user.
- Do not remove auth code. `test_wiring.py` (anonymous rejected) must keep passing with flag off.
- Authored-lines heuristic ~400; docs/tests alongside behavior.

## Execution config
- TDD: enabled (strict, project config). Runners: `uv run pytest` (backend), `npm test` in `frontend/` (vitest).
- Route: delegated direct, one writer (4+ non-trivial files across backend, frontend, launcher, README).

## Tasks
- [x] T1 Backend: setting + synthetic session in `deps.py` + config validation + tests (RED first)
- [ ] T2 Frontend: skip login when session already present + test
- [ ] T3 Launcher: export flag, bind 127.0.0.1; README + `.env.example` note
- [ ] T4 Verify full suites, commit per work unit, PR

## Progress / evidence
- T1: RED observed (7 failed, 1 passed in tests/admin_api/test_auth_disabled.py), then GREEN. Full backend `uv run pytest -q`: 1905 passed. ruff check/format clean. mypy: 97 pre-existing errors elsewhere, none new in touched files. CSRF is skipped when the flag is on. Commit: see git log (T1).

## Next step
T2.
