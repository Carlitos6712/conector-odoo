# Changes needed in the SUWE clone for the connector

The connector talks to a **clone** of SUWE (the mock API plus its frontend), not to the original app.
This page lists every change made to that clone, where it lives and how to repeat it on another machine.
Keep it up to date: each time development needs a new change in the clone, add it here in the same
commit.

Clone layout on the development machine:

| Part | Path | Port |
| --- | --- | --- |
| Mock API (FastAPI, in memory) | `~/Escritorio/suwe/api_mock` | 8000 |
| SUWE frontend (clone) | `~/Escritorio/suwe/app_suwe` | 8080 |

The mock folder is **not a git repository**. A pristine copy was taken before the first edit at
`~/Escritorio/suwe/api_mock.orig`. All test data in the clone was created for testing.

## 1. Applied changes

### 1.1 Mock API: write endpoints for clients

| | |
| --- | --- |
| File | `api_mock/routes_org.py` (only file changed) |
| Why | The mock only had `GET` and `POST` on `/api/v1/organization/clients`. The connector needs edit and delete so a change made in the connector can be written back to SUWE. Without these routes the mock catch-all (`main.py`) answers any unknown `/api/v1/**` request with a fake `200`, so the connector would believe the write worked. |
| Added | `PATCH /api/v1/organization/clients/{client_id}` and `DELETE /api/v1/organization/clients/{client_id}` |
| PATCH | Accepts `name`, `legal_name`, `tax_id`, `address`, `city`, `province`, `country`; aliases `client` (name) and `cif` (tax_id) also keep the list-view duplicates in sync; sets `updated_at`; returns the client detail shape. Unknown id gives `404`. |
| DELETE | Removes the client from `CLIENTS` and `CLIENT_BY_ID`, returns `{"deleted": true, "uuid": ...}`. Unknown id gives `404`. Stores, contacts and user access that point at the client are left orphaned (acceptable for a mock). |

Apply on another machine (from the folder that contains `api_mock/`), then rebuild the container:

```bash
patch -p1 < /path/to/conector-odoo/docs/suwe/api_mock-clients-write.patch
cd api_mock && docker compose up -d --build
```

Check it:

```bash
curl -s -X PATCH localhost:8000/api/v1/organization/clients/<uuid> \
  -H 'content-type: application/json' -d '{"city":"Sevilla"}'
curl -s -X DELETE localhost:8000/api/v1/organization/clients/<uuid>   # then GET -> 404
```

The patch file is `docs/suwe/api_mock-clients-write.patch`. To undo, `patch -R -p1` with the same file, or
restore the pristine copy.

### 1.2 Connector profile: `clients` resource with write endpoints

This is **connector data**, not a SUWE change, but without it the connector cannot write to SUWE. It
lives in the connector database (resource of the `suwe-mock` connection, profile id `2` here). Set it
through the admin API (or the Resources page):

```bash
curl -X PUT http://localhost:8001/admin/api/profiles/<suwe-profile-id>/resources/clients \
  -H 'content-type: application/json' -d '<config below>'
```

Endpoints of the resource (all relative to the connection base URL `http://localhost:8000/api/v1`):

| Operation | Method and path |
| --- | --- |
| list | `GET /organization/clients` (items in `items`, `id_field` = `uuid`, page pagination with `page` and `page_size`) |
| get | `GET /organization/clients/{id}` |
| create | `POST /organization/clients` |
| update | `PATCH /organization/clients/{id}` |
| delete | `DELETE /organization/clients/{id}` |

Keep the rest of the existing config (pagination, `items_path`). The previous config only had the list
endpoint.

### 1.3 Connector job: `suwe-clients-to-odoo` made bidirectional

Also **connector data**. Write-through from the Records page only reaches the counterpart of an enabled
job with direction `bidirectional` and a `reverse_mapping`. Repeat on every machine:

1. Save the mapping `res.partner_to_clients` (`PUT /admin/api/mappings/res.partner_to_clients` with
   `source_profile_id` = Odoo profile, `target_profile_id` = SUWE profile). Source `res.partner`, target
   `clients`, direct rules: `name`->`name`, `city`->`city`, `vat`->`tax_id`, `street`->`address`,
   `ref`->`uuid` with `required: true`.
2. `PUT /admin/api/jobs/<job-id>` with the job unchanged except `direction: "bidirectional"` and
   `reverse_mapping: {"name": "res.partner_to_clients", "version": null}`.

3. Mark the partners written by the OTHER `suwe-*` jobs so the reverse pass can skip them. Marker: the
   Odoo `res.partner` field `function` (Job Position, free char, unused by every SUWE mapping) set to
   `suwe-sync`. For each forward mapping of jobs `suwe-groups-to-odoo`, `suwe-stores-to-odoo`,
   `suwe-kyc-to-odoo`, `suwe-users-to-odoo` and `suwe-partners-to-odoo` (`groups_to_res.partner`,
   `stores_to_res.partner`, `kyc_to_res.partner`, `users_to_res.partner`, `partners_to_res.partner`), add
   the rule `{"target": "function", "expr": {"type": "constant", "value": "suwe-sync"}, "required": false}`
   and `PUT /admin/api/mappings/<name>` (each became version 2; the jobs use `version: null`, so they
   follow the latest). Do NOT add it to `clients_to_res.partner` (job 1), or client partners would be
   skipped too. Then run each of those jobs once (`POST /admin/api/jobs/<id>/runs` with
   `{"dry_run": false}`, one at a time): they update the existing partners through the xref and stamp
   them (observed: 8 + 90 + 30 + 40 + 6 updates, 0 failed, 1 new partner for a SUWE group that had never
   been synced).
4. Set the reverse filter on job 1 (`PUT /admin/api/jobs/<job-id>`, whole job body unchanged except):
   `"reverse_record_filter": {"equals": {}, "since": null, "raw": {"domain": [["function", "!=", "suwe-sync"], ["ref", "!=", false]]}}`.
   The second term skips Odoo partners without a `ref` (native partners 1, 3 and 7), which would otherwise fail the
   required `ref` -> `uuid` rule on every run and leave each run as `partial`.
   Odoo `!=` also matches empty values, so unmarked partners pass.

A job has a `reverse_record_filter` (same shape as `record_filter`: `equals`, `since`, `raw`; empty by
default) applied only to the reverse pass, so its field names belong to side B (for this job, Odoo
`res.partner`; `raw` takes an Odoo domain). The write-through from the Records page is not filtered.

What the reverse pass of job 1 still picks up: partners with a `ref` and no marker, that is the SUWE
client partners (expected), plus any partner created by hand with a `ref`. Native partners without `ref`
fail the required `ref`->`uuid` rule and are not created. A new partner written by another `suwe-*` job
is marked on its first run (the mapping carries the marker); a partner written before step 3 stays
unmarked until its job is re-run. The marker is a convention: someone clearing or editing `function` on
a marked partner makes it eligible again.

5. Resolve edits made on both sides with the most recent one: `PUT /admin/api/jobs/<job-id>` (whole job
   body unchanged except) `"conflict_rule": "newest_wins"`, `"source_updated_field": "updated_at"` (SUWE
   `clients`) and `"target_updated_field": "write_date"` (Odoo `res.partner`, naive UTC text). A conflict
   only exists when both sides changed since the last sync; then the later timestamp wins. Equal,
   missing or unparsable times still write nothing and record a non-retryable `conflict` error.

   Why the runner re-reads the record: the SUWE `clients` LIST items carry no `updated_at` (only the
   detail endpoint does) and the forward pass reads its source records from the list. Under
   `newest_wins`, when the source record has no value in `source_updated_field`, the runner fetches the
   full record by id and reads the time from it; without that fallback every conflict would be flagged.
   Nothing is fetched when the field is present, and other conflict rules are unaffected.

Restore: `PUT` job 1 with `reverse_record_filter` empty (`raw: null`), and optionally `direction: "a_to_b"`
and `reverse_mapping: null`. To drop the marker, `PUT` the mappings of step 3 without the `function` rule
(new versions) and re-run the jobs; the `function` values already written stay in Odoo until edited.

## 2. Behaviour of the mock you must know

- State is **in memory**: restarting the container resets the data to the fixtures and drops created,
  edited and deleted clients. Re-run the connector jobs afterwards.
- No authentication: the mock ignores `X-API-Key`.
- `POST /organization/clients` takes the new id from the body key `client_id` (not `uuid`), has no
  required fields and no uniqueness check on `tax_id` or `name`.
- Only `clients` has write routes. Other entities (stores, groups, users, KYC) are read-only in the mock.

## 3. Known caveats

- The Resource edit form in the connector UI does not carry `delete_endpoint`: saving a resource from
  the UI drops it. Re-apply it through the API until the form supports it (planned, see section 4).

## 4. Pending and future changes in the clone

Update this list as development goes on.

- [ ] Create from the connector: the mock reads `client_id` for the id, so the create mapping must send
  `client_id` (mapped from the Odoo side) or the mock will generate its own id and the xref must read the
  new `uuid` from the response. Decide in the write-through task (T4 of `odd/tasks/bidirectional-records.md`).
- [ ] If bidirectional edit or delete is needed for other entities (stores, groups, users), the mock
  needs the same `PATCH` and `DELETE` routes for each one. Not planned yet.
- [ ] Optional hardening of the mock if every client is deleted: `create_client` and
  `routes_kyc_services.py` use `CLIENTS[0]` and fail on an empty list.
- [ ] Connector UI: resource form must include `delete_endpoint` (T5).
- [ ] When this is applied on a real SUWE (not the mock), the real API must expose equivalent update and
  delete endpoints; adjust the resource config paths accordingly.

## 5. Cleanup of run 39 (test data)

Run 39 of job 1 (`suwe-clients-to-odoo`, manual, 2026-10-06 12:56 UTC) ran the reverse pass before the
marker and the reverse filter existed. It pushed Odoo partners written by the other `suwe-*` jobs
(groups, stores, KYC, users, partners) into SUWE `clients`: the mock went from 38 to 214 clients.

**Identification.** The mock ignores the `uuid` sent on create and generates its own, so `ref` -> `uuid`
does not match. The evidence used instead: job 1 xref rows (`source_id` = SUWE uuid, `target_id` = Odoo
partner id) whose partner carries the marker `function = suwe-sync` (174), cross-checked with the mock
`created_at` (all `2026-10-05T10:00:00Z`, the mock's fixed value, unlike the fixtures which have
December to June dates). Result: 174 clients, 0 of them original fixtures. Not deleted on purpose: the
leftovers `Sipay`, `Messi`, `Aena`, `Erik Bocadillo` (no xref, user test data).

**Safety rule.** Never delete these clients through the connector (`DELETE
/admin/api/profiles/2/records/clients/{id}`): job 1 is bidirectional, so write-through would also
delete the linked Odoo partners. Delete them only on the mock itself:
`DELETE http://localhost:8000/api/v1/organization/clients/{uuid}` (no auth, in memory).

**What was done.** 174 sequential `DELETE`s on the mock (all `200`); then the 174 job 1 xref rows
removed with a transaction on `data/admin.db` (`delete from xref where job_id = 1 and
resource = 'clients' and source_id = ?`), after a backup. The Odoo partner list (214) was identical
before and after. A dry-run of job 1 afterwards: created 4 (the leftovers), skipped 72, failed 3
(partners 1, 3, 7 have no `ref`).

**Redo on another machine.** Either restart the mock container (resets its data to the fixtures, then
forget the job 1 xrefs with the SQL above for all job 1 rows that are not original clients), or repeat
the identification (xref rows of job 1 whose target partner has `function = suwe-sync`) and delete those
uuids on the mock directly. Always keep the reverse filter of section 1.3 set before running job 1.
