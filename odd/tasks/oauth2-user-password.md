# oauth2-user-password

## Objective
Let an `oauth2_client_credentials` REST profile authenticate with a username and an app password
(Authentik `client_credentials` + `username`/`password` flow) instead of only client id/secret.

## Why
Colleagues must connect to api_suwe, which only accepts user JWTs (claims `exp`, `sub`, `uuid`). Copying
a token from browser DevTools is too tedious. Authentik issues a user JWT from an app password.

## Scope / constraints
- No new `AuthMethod`. In `oauth2_client_credentials`: when `username` + `password` are set, send
  `grant_type=client_credentials&client_id&username&password[&scope]`; otherwise keep client id/secret.
  Existing profiles must behave exactly as before.
- `username` is non-secret (profile column + migration, repository, schema, UI). `password` reuses
  the existing vault secret field `password`. Never log or return the password.
- Frontend wizard: show username/password fields for this method; client secret optional when they are set.
- Docs alongside behavior (README). Authored-lines heuristic ~400.

## Execution config
- TDD: enabled (strict, project config). Runners: `uv run pytest` (backend), `npm test` / `npm run typecheck` / `npm run lint` in `frontend/`.
- Route: delegated direct, one writer (4+ non-trivial files across backend, migration, frontend, docs).
- Branch: feat/oauth2-user-password (cut from feat/vault-key-setup HEAD; main checkout blocked by unrelated local edits).

## Tasks
- [x] T1 Backend: domain `username`, TokenAuth password grant, repository + migration, schemas, probe, tests (RED first)
- [x] T2 Frontend: wizard/form/types fields + tests
- [x] T3 README doc + verify full suites, work-unit commits (PR left to user)

## Progress / evidence
- Route: delegated direct, single writer (4+ non-trivial files across backend, frontend, docs).
- T1 (32d9735): RED observed first (10 failed: ConnectionProfile had no `username`), then GREEN; full backend 1938 passed. `username` lives in `options_json` like the other non-secret options (token_url, scope), so no new DB column or migration was needed; repository, view, schemas, TokenAuth, probe updated.
- T2 (1d75198): RED observed (2 failed in ConnectionWizard.test), then GREEN; frontend 632 passed, typecheck and lint clean.
- T3 (925954c): README section added; final suites re-run (see report).

## Next step
User review and PR.
