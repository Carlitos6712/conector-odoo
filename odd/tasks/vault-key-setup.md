# vault-key-setup

## Objective
Let an admin create the credential-vault encryption key from the frontend, so storing connection secrets does not require editing `.env`.

## Problem
Without `ENCRYPTION_KEY` the vault raises `VaultNotConfigured` (503 `vault_not_configured`) and the connection wizard shows "The credential vault is not configured on the server."

## Design (approved by user)
- Backend generates a Fernet key and stores it in a separate file with mode `0600` in the data directory, outside the SQLite DB.
- `ENCRYPTION_KEY` from the environment always wins when set.
- No arbitrary key paste from the UI.
- The endpoint only works when no key is configured yet (no env key, no key file): never orphan existing secrets.
- Front: "Generate key" action shown when the vault is not configured (wizard error state + settings).

## Constraints
- Strict TDD enabled; runners: `pytest` (backend), `vitest run` (frontend).
- Artifacts in English. ~400 changed lines is a planning heuristic only.
- Key material never logged or returned by any API.

## Tasks
- [x] T1 Backend: key file store + vault resolution (env > file) + status/generate admin endpoints, with tests (commit 6dfafc6)
- [x] T2 Frontend: vault status + generate button, wired into wizard error state, with tests (commit f166d69)
- [ ] T3 Docs: README / .env.example note

## Route
T1, T2: delegated direct (one writer, 2+ non-trivial files). T3: inline.

## Progress
Branch `feat/vault-key-setup`. T1 and T2 done (pytest 1926 passed, ruff/mypy clean; vitest 630 passed, tsc/eslint/prettier clean). T3 pending.
