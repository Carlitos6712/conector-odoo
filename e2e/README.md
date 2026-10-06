# End-to-end tests (Playwright)

Drive the real admin UI (built `frontend/dist` served by the FastAPI app) through the main flow:
connect the SUWE fake API, define the `clients` resource, map it to `res.partner`, dry-run, run,
check the history and the records in Odoo, and run again to prove idempotency. A second test
covers the wrong-password error and the read-only operator role.

## What runs where

| Piece | How it starts | Port |
| --- | --- | --- |
| Connector backend + built frontend | `scripts/start-backend.mjs` (Playwright `webServer`): fresh SQLite DBs in `e2e/.state/`, fresh vault key, bootstrap admin, `ADMIN_COOKIE_SECURE=false`, scheduler off | 8100 |
| Odoo | `tests/e2e_support/fake_odoo.py` (Playwright `webServer`): in-memory JSON-RPC fake with `res.partner` | 8169 |
| SUWE fake API | **external**: the `api_mock` Docker container, not started by the tests | 8000 |

Odoo is faked on purpose. A developer Odoo may be running on `:8069`, but the suite writes 37
partners and must start from an empty model every time, so it never touches a real instance. The
fake implements only what the connector's generic adapter calls (`authenticate`, `fields_get`,
`search_read`, `read`, `create`, `write` on `res.partner`, `ir.model` for discovery) and is covered
by `uv run pytest tests/e2e_support`.

If the SUWE fake is not reachable at `http://localhost:8000`, the SUWE-dependent tests are
**skipped** with a message (`E2E_SUWE_URL` overrides the address); they never pass vacuously.
Assertions read the live client count and uuids from the fake instead of hard-coding them.

## Run

Prerequisites: `uv sync`, Node 20+, the SUWE fake up on `:8000`.

```bash
cd e2e
npm ci
npx playwright install chromium   # once
npm test                          # builds ../frontend, then runs the suite
npm run test:only                 # same, without rebuilding the frontend
npm run test:headed               # watch it
npm run report                    # open the HTML report of the last run
```

Environment overrides: `E2E_BACKEND_PORT` (8100), `E2E_ODOO_PORT` (8169), `E2E_SUWE_URL`,
`E2E_ADMIN_USER`, `E2E_ADMIN_PASSWORD`. The ports must be free: servers are never reused, so a
stale one cannot leak data between runs.

Traces are kept on the first retry (1 retry in CI), screenshots on failure; `test-results/`,
`playwright-report/` and `.state/` are git-ignored. The suite is serial by design (one backend,
one fake Odoo, files run in name order: `02-*` reads what `01-*` created).
