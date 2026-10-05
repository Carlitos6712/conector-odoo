# Feature: generic-connector-admin

## Objective
Link Odoo with arbitrary external REST APIs (first target: SUWE) and add a web frontend to configure connections, map data, run and monitor transfers.

## Constraints
- Hexagonal: new capabilities enter via domain ports; no framework imports in domain.
- Keep SQLite, in-process scheduler, frontend served by same container.
- Odoo adapter is model-generic (any model, fields via `fields_get`). Decided by user.
- Admin users local (argon2 hash, session cookie). Roles: admin, operator (read-only).
- Existing Odoo repositories and HMAC webhook intake untouched beyond new port needs.
- Conventional Commits, no AI attribution. Tests alongside behavior.
- UI Spanish by default, i18n-ready; code/identifiers English.

## Authorized scope
Whole plan below, approved by user. Push/PR/merge remain user decisions.

## TDD
Mode: enabled (project config, Strict TDD). Runner: `uv run pytest` (backend); frontend runner TBD in F1 (vitest).

## Delivery strategy
ask-on-risk (default). Chain strategy chosen by user: feature-branch-chain (slice PRs target the feature branch; feature branch merges to main last). Slice boundaries: slice 1 = B1+B2 (94fad86, d57ea4c, e16758d).

## Tasks
Backend
- [x] B1 Versioned SQLite migrator + schema (profiles, resources, mappings, jobs, runs, run_errors, xref, admin_users)
- [x] B2 Secret vault (Fernet) + connection profile CRUD + test-connection with failing step
- [x] B3 Domain ports RecordSource/RecordSink + generic Record
- [x] B4 REST adapter (page/offset/cursor, retry network-only, idempotency key, error normalization, auth: API key/Bearer/client credentials/OIDC); verify SUWE M2M against fake OIDC
- [x] B4b REST hardening from B4 review (token 5xx/429, bad URL errors, per-strategy pagination, test nits)
- [x] B5 Generic Odoo adapter (any model, fields_get) built from profile
- [x] B6 Resource catalog + OpenAPI importer
- [x] B7 Mapping engine (direct, constant, trim, case, date, cents, lookup, concat), versioned JSON, dry-run
- [x] B8 Sync runner (upsert key, xref, idempotent, resumable, per-record errors, retry-failed, conflict rule)
- [ ] B9 Triggers: manual, cron scheduler, webhook trigger
- [ ] B10 /admin/api + admin login + roles
Frontend
- [ ] F1 Vite/React/TS/Tailwind/shadcn scaffold, i18n (es), TanStack Query, static serving from FastAPI
- [ ] F2 Connections wizard
- [ ] F3 Resources browser
- [ ] F4 Mapping editor
- [ ] F5 Jobs wizard
- [ ] F6 Runs and detail
- [ ] F7 Dashboard
- [ ] F8 Settings
Delivery
- [ ] D1 Playwright e2e vs SUWE fake
- [ ] D2 README + architecture diagram
- [ ] D3 docker-compose multi-stage with Node

## Acceptance
- `uv run pytest` green; mapping engine, adapter pagination, xref upsert, dry-run covered.
- Frontend lint, typecheck, unit tests green; one Playwright e2e (connect SUWE fake, map clients -> res.partner, dry-run, run, see in history).
- README updated (diagram, setup, security, adding a target API).
- `docker-compose up` brings everything up.

## Route log (task -> route, trigger evidence)
- B1: delegated direct (single writer; trigger: 2+ non-trivial files, ~10 files touched). TDD RED observed (collection ImportError), then GREEN.
- B2: delegated direct (single writer; trigger: 2+ non-trivial files, ~20 files). TDD RED observed (migrator race: table already exists; startup leak: store still open; profiles: collection ImportError), then GREEN.
- B3: delegated direct (single writer; trigger: 2+ non-trivial files, domain + fake + tests). TDD RED observed (collection ImportError: RecordRejected), then GREEN.

- B4: delegated direct (single writer; trigger: 2+ non-trivial files, ~20 files). TDD RED observed (collection ModuleNotFoundError domain.resources; 7 probe tests failed on 404/429/other 4xx/InvalidURL), then GREEN.
- B4b: delegated direct (single writer, same run as B5). TDD RED observed (7 failures: token 429/5xx raised RemoteAuthError, InvalidURL/UnicodeError/UnsupportedProtocol leaked or retried), then GREEN.
- B5: delegated direct (single writer; trigger: 2+ non-trivial files). TDD RED observed (collection ImportError: infrastructure.odoo.records), then GREEN.
- B6: delegated direct (single writer; trigger: 2+ non-trivial files, ~25 files incl. fixtures). TDD RED observed twice (collection ModuleNotFoundError: application.resources; then infrastructure.openapi), then GREEN.
- B7: delegated direct (single writer; trigger: 2+ non-trivial files, ~20 files). TDD RED observed (collection ModuleNotFoundError: domain.mapping; later domain.mapping_codec/mapping_validation; then application.mappings + infrastructure.mappings), then GREEN.
- B8: delegated direct (single writer; trigger: 2+ non-trivial files, ~22 files). TDD RED observed per stage (collection ImportError SyncJobInvalid; ModuleNotFoundError application.sync_runner; 13 failures for resume/retry/cancel; 14 failures for bidirectional), then GREEN. Migration-4 test written alongside the migration (no separate RED).

## Commits
- B1: 94fad86 feat(db): add versioned migrator and admin schema
- B2: d57ea4c fix(db): serialize concurrent migrations and release stores on startup failure
- B2: e16758d feat(profiles): add secret vault, connection profile CRUD and connection probes
- B3: 3899c64 feat(domain): add generic record model and source/sink ports
- B4: 9c4edf4 feat(rest): add generic REST record adapter with pagination, auth and resilience
- B4: 867f88d fix(profiles): stop treating 404/429/other 4xx as accepted credentials in the REST probe
- B4b: 022893b fix(rest): map token endpoint 5xx/429 and bad URLs to RemoteUnavailable, split pagination per strategy
- B5: e3f40fb feat(odoo): add model-generic Odoo record adapter and profile-based factory

- B6: 661782e feat(resources): add resource catalog with validation, preview and Odoo model discovery
- B6: 1056fad feat(openapi): import resource candidates from OpenAPI 3.x and Swagger 2.0 documents
- B7: cd5d3b6 feat(mapping): add mapping engine with transforms, validation, dry-run and versioned JSON codec
- B7: fd71cb1 feat(mapping): add versioned mapping repository, use cases, dry-run service and mapping suggestions
- B8: 5260808 feat(sync): add sync job domain, migration 4 and job/run/xref repositories
- B8: a27892c feat(sync): add sync runner core with upsert, xref, idempotent skip, error isolation and dry-run
- B8: 31d4e4d feat(sync): add resume, retry-failed, cancel and only-records to the sync runner
- B8: cd76ee4 feat(sync): add bidirectional sync with echo prevention and conflict rules

## Progress / verification
Baseline: 612 passed on branch start.
B1: 632 passed; ruff check/format clean; mypy src clean (parent spot check: 632 passed).
B1 review: tier high (hot_path false positive on test filename), consent granted, 4-lens native review approved, acknowledged. Reviewed boundary now 94fad86.
B1 non-blocking findings (fold into B2): startup leak (open_admin_database after build_container in main.py lifespan; close container on failure), concurrent migrate race (migrator.py:44-53, re-check version inside BEGIN IMMEDIATE), circular import note migrator.py:38, comment unexplained defaults versions.py:100-103.

B2: 703 passed; ruff check/format clean; mypy src clean. B1 findings folded in. Added migration 2 (options_json: odoo db/login, token_url, scope, api_key_header, secret field names). Odoo probe uses JSON-RPC; no HTTP routes or Container wiring yet (B10). ~1000 authored lines (vault, repo, 2 probes, use cases, 70 tests), over the 400 heuristic because the task bundles 5 coherent units.

B2 review: tier medium, slice_budget_reached, consent granted, native review approved, acknowledged. Reviewed boundary now e16758d. Non-blocking findings (fold into B4): rest_probe auth step treats any non-401/403/5xx (e.g. 404, 400, 429) as "credentials accepted" (rest_probe.py:158-173); `_check_auth` only catches httpx.TransportError, not InvalidURL/UnicodeEncodeError (:138-155); weak at-rest assertion in tests/profiles/test_repository.py:75-76.
B3: 730 passed; ruff check/format clean; mypy src clean. Domain: records.py (FieldType, FieldSpec, ResourceSchema, Record with deep-copied read-only fields + dotted get, RecordPage, RecordFilter), RecordSource/RecordSink/RecordEndpoint runtime_checkable Protocols, errors ResourceNotFound/RecordRejected/RemoteUnavailable/RemoteAuthError. Reusable tests/unit/fakes_records.py InMemoryRecordEndpoint (use in B7/B8).

B3 review: tier medium (executable change in errors.py), slice_budget_reached, consent granted, approved, acknowledged. Reviewed boundary now 3899c64. Parent spot check: 730 passed. Non-blocking: fake endpoint reject ordering (tests/unit/fakes_records.py:63-66), iter_batches size handling (:44-51), nested-copy test weak (tests/records/test_records.py:59-62). Fold into B7/B8 when reusing the fake.

SUWE fake findings (B4 verification, observed with curl): API :8000 serves /api/v1/* with NO auth enforced; pagination `{items,total,page,page_size,total_pages}` with page/page_size; clients at /api/v1/organization/clients (uuid ids). Fake OIDC :9000 has only /application/o/{authorize,token,userinfo}/ and /suwe/{jwks,end-session}/ (no discovery doc); token endpoint answers `unsupported_grant_type` for client_credentials and password => NO machine-to-machine flow in the fake. BLOCKER for production: real SUWE/Authentik service-token flow unconfirmed. Dev/e2e unaffected (fake API needs no auth; use Bearer dummy token). Options for user later: (a) Authentik client_credentials/service account on real SUWE, (b) static API key/long-lived token issued by SUWE, (c) refresh-token flow after one interactive login.

B4: 817 passed; ruff check/format clean; mypy src clean. Domain resources.py (ResourceConfig, PaginationConfig, EndpointSpec) + ResourceConfigProvider port; infrastructure/rest/{auth,http,errors,endpoint,factory,jsonpath}.py. B2 review findings folded (probe judge 404/429/4xx, InvalidURL/UnicodeError, at-rest assertion). SUWE integration check RAN (fake up on :8000): PAGE strategy, id_field=uuid, all 37 clients iterated; marker `integration` registered (auto-skips when unreachable). Notes: OIDC token endpoint = profile.token_url else discovery at issuer_url (default base_url); probe does not reuse the auth builder yet. ~1860 authored lines (adapter ~700, 80 tests), over the 400 heuristic because auth, resilience, pagination and error mapping are one coherent adapter; split in 2 commits.

B4 review: tier high (auth hot path), consent granted, 4-lens review approved, acknowledged. Reviewed boundary now 867f88d. Parent spot check: 817 passed. Non-blocking findings, to fix in a small hardening commit before slice PR (B4b, not yet done): (1) token endpoint 5xx/429 raised as RemoteAuthError, should be RemoteUnavailable (auth.py:118-125); (2) RestHttpClient._send only catches httpx.TransportError, InvalidURL/UnicodeError escape as raw exceptions (http.py:120-135); (3) _pages handles 4 strategies in one method, split per strategy (endpoint.py:110-160); (4) test nits: tests/rest/helpers.py:102-110, tests/profiles/test_probes.py:178-184. Resilience note (idempotent GET not retried on 429/502/503): matches user spec "retry on network errors only"; keep, mention in README.

B4b: 827 passed; ruff check/format clean; mypy src clean. Invalid URL/headers/unsupported protocol -> RemoteUnavailable (config problem of the target, never retried, message without URL text). No GET status retries (user spec).
B5: 881 passed; ruff check/format clean; mypy src clean. infrastructure/odoo/records.py (OdooRecordEndpoint: fields_get schema cache, keyset iter_batches, normalization many2one->int / False->None, None->False on write, many2many id list -> [6,0,ids], write denylist with allow_system_model_writes flag, error mapping) + build_odoo_endpoint in odoo/factory.py. ~360 source lines + ~550 test lines, over the 400 heuristic because tests cover every field type, filter and error path. No routes, no Container wiring (B10), no catalog persistence (B6).

B4b+B5 review: tier high (auth hot path), consent granted, 4-lens review approved, acknowledged. Reviewed boundary now e3f40fb. Parent spot check: 881 passed. Non-blocking (cosmetic, defer to cleanup): odoo/records.py:62, rest/auth.py:118-121 ordering, odoo/factory.py:66-90 transport construction duplicated with odoo_probe, tests/adapters/test_odoo_record_endpoint.py:530-546 private access.

B6: 1001 passed; ruff check/format clean; mypy src clean. Migration 3 adds resources.source (manual|openapi) and updated_at; config stays versioned JSON (domain/resource_codec.py, validation + codec). Profile delete with catalog entries is refused (FK -> ProfileInUse), consistent with B2. Catalog is REST-only (Odoo models are discovered via ir.model). Importer: infrastructure/openapi/{loader,schemas,importer}.py, pyyaml safe_load only, 5 MB cap, http/https only, local $ref only. Fixtures: tests/fixtures/suwe_openapi_real.json (trimmed copy of the live fake spec; it has NO query params or response schemas, so pagination NONE + warnings) and suwe_openapi_enriched.json (same paths plus the page/page_size params and {items,total,page,page_size,total_pages} schema observed with curl). Live check against the fake: 39 candidates, 124 warnings with base_path=/api/v1. ~1300 src lines + ~1230 test lines, over the 400 heuristic: catalog, use cases and importer are two coherent units (2 commits).

B6 review: tier medium (pyproject config), slice_budget_reached, consent granted, approved, acknowledged. Reviewed boundary now 1056fad. Parent spot check: 1001 passed. Non-blocking, to fix in B10 hardening: openapi/loader.py:35-43 fetch follows redirects (SSRF/redirect to internal host; disable redirects or revalidate each hop); resources/repository.py:77-82 one corrupt row aborts list (skip+report instead); migrations/versions.py:120-127 updated_at NULL on migrated rows.
Note: live SUWE fake spec has no query params/response schemas, so OpenAPI import yields pagination NONE and mostly warnings; UX must let user set pagination/items_path manually (F3/F4).

B7: 1189 passed; ruff check/format clean; mypy src clean. Domain (stdlib only): mapping.py (Expr: direct/constant/concat/transform; 16 steps incl. to_cents/from_cents with Decimal ROUND_HALF_UP, lookup policies, coalesce), mapping_engine.py (apply_mapping, never raises on data, per-rule error isolation, nested dotted targets), mapping_codec.py (versioned JSON, errors carry the path), mapping_validation.py (validate_definition + dry_run with FieldSpec type/choices checks). Persistence: no migration needed (mappings table: unique name+version, definition_json); SqliteMappingRepository (identical-to-latest save returns latest; delete refused with MappingInUse when ANY version is referenced by sync_jobs.mapping_id, explicit query so it does not depend on the FK pragma). application/mappings.py: Save/Get/List/ListVersions/Delete/DryRun use cases (schemas and samples via injected callables) + suggest_mapping. No routes, no Container wiring (B10), no sync runner (B8). ~1400 src lines + ~1250 test lines, over the 400 heuristic: engine, validation/dry-run, codec, persistence and use cases are separate coherent units (2 commits).
Notes for B8/B10: `coalesce` is a step (not a top-level expr); None/missing source values are omitted from output (never sent as null), so clearing a remote field needs an explicit Constant/Default; SaveResult.created is computed from get-then-save (not atomic across concurrent saves of the same name; fine for single-admin use).

B7 review: tier medium, slice_budget_reached, consent granted, approved, acknowledged. Reviewed boundary now fd71cb1. Parent spot check: 1189 passed. Non-blocking: mapping_engine.py:185-188 huge-exponent int conversion (cap/guard in hardening); mappings/repository.py:48-52 "no commit on write" is moot because admin DB connection is autocommit (isolation_level=None), keep that invariant documented.

B8: 1282 passed; ruff check/format clean; mypy src clean. Domain sync.py (SyncJob, triggers manual/schedule(cron validated)/webhook, ConflictRule, Direction) + sync_runs.py (RunStatus, counters, XRef, redact_payload); migration 4 (job resources/mapping names/reverse mapping/updated-at fields, run conflicts/checkpoint/heartbeat/parent/options/error/sample/cancel flag, run_errors side/kind/retryable, xref content_hash/reverse_hash, UNIQUE sync_jobs.name). Repos in infrastructure/sync/{jobs,runs,locks}.py (shared per-connection lock; job delete refused with SyncJobInUse when runs exist; MappingInUse now also checks reverse_mapping_id). application/sync_runner.py: algorithm documented in the module docstring. xref semantics: content_hash = forward mapping of A at last sync, reverse_hash = reverse mapping of B; echo prevention and conflict detection both compare them. Resume = skip until checkpoint last_id (no remote cursor in RecordSource), replay if that id vanished; stale run (no heartbeat for 15 min) is resumable and does not block a new run. Fake endpoint extended (reject_when hook, get/update counters, batch_size check). ~3460 lines over 4 commits (about 1500 src, 1950 tests), over the 400 heuristic: domain+migration+3 repos, runner core, resume/retry/cancel and bidirectional are separate coherent units.
Notes for B9/B10: runner takes injected EndpointFactory (profile id -> RecordEndpoint), clock and sleep; no Container wiring, no routes. No automatic incremental `since` (filter.since only; checkpoint stores max_updated_at for later use). Reverse pass ignores job.record_filter (its field names belong to side A). Dry-run does not simulate xref effects across passes. SQLite connection lock registry keeps connections alive (sqlite3.Connection is not weak-referenceable).

## Next step
B9 Triggers: manual, cron scheduler, webhook trigger (use SyncRunner.run with TriggerKind, JobAlreadyRunning handling).
