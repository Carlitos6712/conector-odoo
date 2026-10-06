# record-management

## Objective
Let an admin edit and delete INDIVIDUAL records of a connected target (Odoo models first) from the
connector admin API and UI, so migrated data can be corrected or removed one record at a time.

## Why
After migrating SUWE data into Odoo there is no way to fix or remove a wrongly migrated record from the
connector. User decision: NO bulk delete and NO cascade when a connection is deleted (an Odoo backup
is the safety net for mass cleanup; document how to take one). Deleting a connection keeps working as
today and never touches remote data.

## Scope / constraints
- Port `RecordEndpoint` (`domain/ports.py`) gets `delete(resource, id)`. Odoo adapter
  (`infrastructure/odoo/records.py`) implements it with `unlink`; Odoo refusals (record referenced by
  invoices/orders, access rules) map to a clear per-record error, never a silent success. REST endpoints
  raise "does not support delete" (no delete endpoint in the resource config; out of scope).
- Admin API under `/admin/api/profiles/{profile_id}/records/{resource}`: list (search + pagination),
  get one, PATCH (edit fields), DELETE one. Writes are admin-only (operators stay read-only, same as the
  rest of the admin API); CSRF/session rules exactly like other mutating admin routes. Secrets/payloads
  are redacted in logs as elsewhere. NO collection-level delete, NO filter-based delete.
- Stale cross-references: when a record deleted through this API is a sync target, remove the xref
  rows that point to it so the next job run recreates it instead of updating a missing id. Verify how
  `sync_runner` treats a missing target today and keep behavior consistent.
- Frontend page "Records": choose an Odoo connection, enter/pick a model (default `res.partner`),
  search, paginate, edit a record (dialog showing writable fields from the model schema), delete one
  record with an explicit confirmation naming the record. English UI copy plus the existing Spanish i18n
  entries if the project keeps both (follow existing convention).
- README: new section describing the page, plus how to back up Odoo before destructive work
  (verify the real container names with `docker ps` before writing commands).
- Authored-lines heuristic ~400 per task; tests and docs alongside behavior.

## Execution config
- TDD: enabled (strict). Runners: `uv run pytest` (backend); in `frontend/`: `npm test`, `npm run typecheck`, `npm run lint`.
- Route: delegated direct, sequential writers (backend, then frontend); parent verifies between groups.
- Branch: feat/record-management (from fix/rest-resource-guards HEAD). No push/PR (user decision).

## Tasks
- [x] T1 Port + Odoo adapter `delete`, per-record error mapping + tests (RED first)
- [x] T2 Admin API records endpoints (list/get/patch/delete one) + xref cleanup on delete + tests
- [x] T3 Frontend "Records" page: list, search, edit dialog, single delete with confirmation + tests
- [ ] T4 README (feature + Odoo backup how-to), full suites green, work-unit commits
- [ ] T5 Live check against odoo-local on one disposable record (create via job, edit, delete) only after the user confirms

## Progress / evidence
- T1 (route: delegated, backend writer; commit 8a87ce3): RED 11 failed (10 Odoo adapter delete tests + 1 REST), GREEN
  186 passed in the touched suites, full suite 1965 passed. `OdooClient.unlink` is an ARCHIVE shortcut, so the adapter
  calls `execute_kw(model, "unlink")` directly after a `read` existence check (Odoo unlink silently succeeds for missing
  ids): missing/non-numeric id -> ResourceNotFound, refusal (referenced record) -> RecordRejected with Odoo's message,
  AccessError -> RecordRejected "access denied", system models blocked like writes (allow_system_model_writes).
  REST: RecordRejected "does not support delete".
- T2 (route: delegated, backend writer): RED 15 failed + 3 xref tests failed; GREEN 17 API tests + 3 xref tests, full
  suite 1997 passed, ruff clean, mypy only the pre-existing rest/auth.py:225 error. Routes under
  `/admin/api/profiles/{profile_id}/records/{resource}`: GET list (search, limit 1..100 default 25, offset 0..10000;
  returns items, schema, limit, offset, has_more), GET `/{record_id}`, PATCH `/{record_id}` body `{"fields": {...}}`
  (unknown/read-only/id/empty -> 422), DELETE `/{record_id}` -> 204. No collection-level delete. Odoo search uses
  `name ilike`; other cases a client-side case-insensitive match (scan cap 5000).
- Xref: `XRefRepository.forget_target(profile_id, resource, target_id)` deletes xrefs of jobs targeting that
  profile/resource. Runner today: unchanged source + deleted target = skipped forever (stale hash); changed source =
  recreated. Cleanup on delete (also when already gone) makes the next run recreate it. Tested end to end.
- T3 (route: delegated, frontend writer; commit 880ba4c): RED 3 new
  suites failed to load (no implementation), GREEN 659 frontend tests passed (61 files), typecheck and lint clean.
  New `features/records/` (api, hooks, errors, columns, dialogs, page), nav entry + route `/records`, en/es copy.
  Admin-only edit/delete buttons, edit sends only changed writable fields, delete confirmation names record and
  model, states it is permanent, and shows Odoo's refusal. No bulk selection or delete-all anywhere.

## Next step
T4 README/docs.
