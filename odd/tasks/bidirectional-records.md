# bidirectional-records

## Objective
Make create, edit and delete of a record bidirectional between SUWE (mock REST API, resource `clients`)
and Odoo (`res.partner`): a write done on the Records page on one side is also applied to its
counterpart through the sync xref (write-through), without needing a job run.

## Why
User report: a client edited from the connector changed only in Odoo; SUWE kept the old value. The
Records page writes only to the profile it targets (by design of `record-management`). The SUWE mock has
no PATCH/DELETE on `/organization/clients/{id}` (its catch-all answers a fake 200), and the `clients`
resource config has no write endpoints.

## Authorization (user, this session)
- The SUWE app at http://localhost:8080 is a clone; its data is test data created by the assistant.
- The assistant may edit the mock and test data, provided every change is documented here.
- NOTHING is pushed to any remote. Local changes and local commits only.

## Scope / constraints
- Mock `/home/carlos/Escritorio/suwe/api_mock` is NOT a git repo. Backup taken BEFORE any edit:
  `/home/carlos/Escritorio/suwe/api_mock.orig` (restore with `rm -r api_mock && cp -a api_mock.orig api_mock`).
- Edited side wins (explicit user action). Counterpart failure never rolls back the primary write: the
  response carries a warning and the xref hash stays stale so the next job run reconciles.
- Echo prevention: after the counterpart write, upsert the xref with BOTH hashes recomputed (same as
  `SyncRunner._save_xref`). Reuse that logic, do not duplicate it.
- Only enabled jobs with direction `bidirectional` and a `reverse_mapping` take part. Multiple matching
  jobs: apply to every one, report per job.
- Delete: needs `delete_endpoint` in `ResourceConfig`; xref cleanup for both sides (`forget_target`
  only matches the B side today). Counterpart already gone = success. Counterpart refused (Odoo
  `unlink` on a referenced partner) = keep xref, warn.
- No bulk delete, no cascade on connection delete (unchanged decision of `record-management`).
- Authored-lines heuristic ~400 per task; tests and docs alongside behavior.

## Execution config
- TDD: enabled (strict, project config). Runners: `uv run pytest` (backend); in `frontend/`:
  `npm test`, `npm run typecheck`, `npm run lint`. Mock has no tests: verify with curl.
- Route: delegated direct, sequential writers; parent verifies between groups.
- Branch: feat/bidirectional-records (from feat/record-management HEAD). No push/PR.
- Delivery strategy: ask-on-risk; forecast >400 lines, but no PR is planned (no push), so slicing is by
  work-unit commit only.

## Tasks
- [x] T1 Mock: PATCH + DELETE `/organization/clients/{id}` (mutate `CLIENTS` + `CLIENT_BY_ID`, set
      `updated_at`, tolerate orphans in stores/contacts/users). Curl-verified. (route: delegated, writer)
- [x] T2 Connector: `delete_endpoint` in `ResourceConfig` + codec + repository + REST sink `delete`
      (404 -> ResourceNotFound) + SUWE `clients` resource config (get/create/update/delete endpoints). RED first.
- [x] T3 XRef `forget_source`/pair cleanup + single-record sync service extracted from `SyncRunner`
      (mapping, write, `_save_xref`). RED first. Commit 216eb3c; tests/sync 176 passed.
- [x] T4 Records use cases: write-through for update/delete, new `CreateRecord` + `POST /{resource}`,
      warnings in the response. RED first. Commit 3eeb955; full suite 2057 passed.
- [ ] T5 Frontend: create dialog, delete/edit copy about counterpart, show warnings.
- [ ] T6 Live check + README section (what propagates, edited-side-wins, warnings, mock changes).

## Progress / evidence
- Mapping done by an explorer agent (read-only). Facts used: mock store is in memory (restart resets to
  fixtures); mock has no auth; mock POST accepts `client_id` for a chosen id and has no uniqueness
  check; `RestRecordEndpoint.delete` is a stub; `forget_target` only matches B-side ids; runner
  recreates a missing target on update (`ResourceNotFound`).
- Branch created and mock backup taken (see Scope).
- T1 (writer, delegated): `api_mock/routes_org.py` only; PATCH + DELETE clients; curl-verified
  (PATCH changes list+detail, DELETE removes, unknown id 404). Container rebuilt then restarted, so the
  mock is back on its fixtures. Exact diff: `docs/suwe/api_mock-clients-write.patch`.
- T2 (writer, delegated): `delete_endpoint` in ResourceConfig, codec, admin schema, OpenAPI importer,
  REST sink `delete`; tests RED first (30 failures) then green. Parent re-ran `uv run pytest -q`: 2008 passed.
- User request (mid-session): document every change needed in the SUWE clone so it can be repeated on other
  machines, and keep future ones listed. Done in `docs/suwe/README.md` (linked from README); update it in
  the same commit as any new clone change.
- User request: push and merge pending work to the connector repo only (the mock is local, not git).
  Chain strategy: stacked PRs to main, merge commits, in order admin-auth-disabled, vault-key-setup,
  oauth2-user-password, rest-resource-guards, record-management (split in 4 slices), then this branch.
- Test-data changes log (live data):
  - SUWE connection `suwe-mock` (profile 2), resource `clients`: get/create/update/delete endpoints added
    (previous config saved in the session scratchpad only; it had just the list endpoint).
  - Earlier manual tests (record-management T5): Odoo partner "Supermercados Aurora" recreated as id 220.
  - Mock data: reset to fixtures by the container restart.
  - Job 1 `suwe-clients-to-odoo` changed from `a_to_b` / no reverse mapping to `bidirectional` with
    `reverse_mapping` = new mapping `res.partner_to_clients` v1 (Odoo `res.partner` -> `clients`: name,
    city, vat->tax_id, street->address, ref->uuid required). No schedule, never run since. Previous job
    JSON saved in the session scratchpad: `job1.before.json` (mapping `clients_to_res.partner` v3 untouched,
    copy in `mapping.clients_to_res.partner.before.json`). Restore: `PUT /admin/api/jobs/1` with the saved
    JSON (without `id`/`next_fire`); optionally `DELETE /admin/api/mappings/res.partner_to_clients`.
    RUN RISK: the reverse pass has no filter; native Odoo partners lack `ref`, so the required rule makes
    them fail mapping (not created), but partners with a `ref` (e.g. from other `suwe-*` jobs) would be
    created as SUWE clients. Do not run job 1 casually.
  - Live check: throwaway client created/edited/deleted from both sides (Odoo partner 223, now gone).
- T4 (writer, delegated): `CreateRecord` + `RecordWrite`; `UpdateRecord`/`DeleteRecord` take `RecordPropagator`;
  `POST /{resource}` (201); PATCH/POST return `{id, fields, propagation[], warnings[]}`; DELETE now returns
  200 `{propagation, warnings}` instead of 204 (T5 frontend and T6 README must reflect it). Delete order:
  primary, `propagate_delete`, then xref forget; if any job `failed`, generic xref cleanup is skipped so a
  refused pair stays linked (other jobs' stale xrefs wait for a run). RED: 14 collection errors + 10 API
  failures; GREEN. Parent re-ran `uv run pytest -q`: 2057 passed. Pre-existing, untouched: ruff E501 in
  `infrastructure/openapi/importer.py:7`, mypy error in `infrastructure/rest/auth.py:225`.

## Pending (found while working)
- Resource form in the UI drops `delete_endpoint` when saving (add to the form; T5).
- Create from the connector: the id field cannot be supplied, so SUWE `client_id` cannot be chosen (see `docs/suwe/README.md` section 4).

## Done outside the T-list (user requests during the session)
- Resources preview: link "View all records" to the Records page (commit d3d22b5).
- Records page: REST resource picker, page size 25/50/100, range line, show-all-columns (commit c6e7217).

## Queued after T6
- Frontend visual restyle (user: logic and sections are fine, style is monochrome with no colors).
  Becomes its own feature document `odd/tasks/frontend-restyle.md` once the palette is decided.

## Next step
T5: frontend create dialog, delete/edit copy about the counterpart, show warnings and the new DELETE 200 body, RED first.
