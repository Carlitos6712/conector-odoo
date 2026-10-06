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

The required `ref`->`uuid` rule limits the reverse leg of a job RUN: Odoo partners without `ref` (native
ones) fail mapping and are not created in SUWE. Partners that do carry a `ref` (for example created by
the other `suwe-*` jobs) are NOT filtered and would be created as clients. Do not run this job unless that
is acceptable. Restore: `PUT` the job back with `direction: "a_to_b"` and `reverse_mapping: null`.

A job now has a `reverse_record_filter` (same shape as `record_filter`: `equals`, `since`, `raw`; empty by
default) applied only to the reverse pass, so its field names belong to side B (for this job, Odoo
`res.partner`; `raw` takes an Odoo domain such as `{"domain": [["is_company", "=", true]]}`). It is set with
`PUT /admin/api/jobs/<job-id>`. No filter is set on this job yet: the partners created by the other
`suwe-*` jobs carry the same fields as client partners (all set `ref`, `is_company`, `autopost_bills`), so
Odoo data alone cannot tell them apart; only persons (`is_company = false`, from `kyc` and `users`) can be
excluded safely. Do not run this job until a discriminator is chosen.

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
