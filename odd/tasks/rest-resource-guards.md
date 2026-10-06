# rest-resource-guards

## Objective
Remove two silent traps found while migrating SUWE data: (1) a REST resource without pagination
syncs only the first page and the run still reports `succeeded`; (2) running a job on selected records
(`only_records`) fails with `RecordRejected` when the resource has no get endpoint.

## Why
Real test (SUWE mock): clients total 36, page size 20 -> first run created 20, no warning. Runs on
selected records failed with "resource ... does not support get" (`_require` in
`infrastructure/rest/endpoint.py`).

## Scope / constraints
- Trap 1: when the strategy is `none` and the list response carries pagination metadata that proves
  more records exist (`total` > items returned, or `total_pages` > 1), surface a warning in the
  resource preview and record a non-fatal warning on the run. Do not change behavior for resources
  that really have no pagination. No automatic strategy switching.
- Trap 2: when a resource has no `get_endpoint`, fetching a record by id falls back to reading the list
  (honoring the configured pagination) and matching `id_field`; if not found return None like the
  existing not-found path. A configured get endpoint keeps priority.
- Reuse existing structures (PreviewOut, run options/errors); English artifacts; tests alongside.
- Authored-lines heuristic ~400.

## Execution config
- TDD: enabled (strict). Runners: `uv run pytest` (backend); frontend `npm test`/`npm run typecheck`/`npm run lint` only if touched.
- Route: delegated direct, one writer.
- Branch: fix/rest-resource-guards (from feat/oauth2-user-password HEAD). No push/PR.

## Tasks
- [x] T1 Trap 2: get-by-id fallback via list when no get endpoint + tests (RED first)
- [x] T2 Trap 1: pagination-missing warning in preview and run + tests
- [x] T3 README troubleshooting rows updated; full suites green; work-unit commits

## Progress / evidence
- T1 (route: delegated, one writer) commit 100df87. RED: 3 failed (RecordRejected "does not support get"), 1 priority test already passing. GREEN: `uv run pytest -q tests/rest` 98 passed. Fallback scans `_pages` with `scan_batch_size`, matches `Record.id`; configured get endpoint keeps priority.
- T2 (route: delegated) commit 107a40e. RED: 11 failed across rest/use-case/API/runner tests. GREEN: full suite 1954 passed. Mechanism: `RestRecordEndpoint.warnings` (deduped; checks `total`/`total_pages` incl. configured paths and common defaults), `PreviewResult.warnings` -> `PreviewOut.warnings`, runner collects `src.warnings` after each pass and `SyncRunRepository.finish(warnings=)` stores them in `options_json.warnings` (shown by run detail `options`). No migration. Frontend untouched.
- T3 README rows/step 2 updated (warning appears; get endpoint optional). Ruff check clean.

## Next step
Review and (user) push/PR; optionally show `warnings` in the frontend preview/run detail.
