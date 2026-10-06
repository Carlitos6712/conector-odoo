# Feature: security-hardening

## Objective
Close the three security gaps left open by generic-connector-admin: per-IP login throttling (S1), an outbound URL policy against SSRF (S2) and vault key rotation (S3).

## Constraints
- Hexagonal: domain stays framework-free (stdlib only); infrastructure holds sqlite/httpx/FastAPI.
- English code, comments, docs. Conventional Commits, no AI attribution. Work-unit commits per task, tests and docs alongside.
- No push. Do not touch containers not started by this work (SUWE fake `api_mock-api-mock-1` is external).

## Authorized scope
S1-S3 below plus README/.env.example/architecture docs and the "open gaps" of odd/tasks/generic-connector-admin.md. Branch `fix/security-hardening` (from main). Push/PR/merge stay user decisions.

## TDD
Mode: enabled (project config, Strict TDD). Runner: `uv run pytest`.

## Tasks
- [x] S1 Per-IP login throttling (sliding window in SQLite, TRUSTED_PROXY_COUNT, 429 generic body, known-IP lockout-DoS mitigation)
- [x] S2 Outbound URL policy (domain policy, DNS resolve + connect-time pinning, default/strict, enforced at every outbound call, 422)
- [x] S3 Vault key rotation (MultiFernet, ENCRYPTION_KEY_PREVIOUS, rotate command, startup check)
- [x] Docs: README security section, env table, .env.example, architecture, close gaps in generic-connector-admin tracker

## Route log
- Tracker created before the first source write. All tasks: single writer (this agent, delegated by the parent orchestrator).

## Commits
- S1: b501fd5 fix(auth): throttle failed logins per client address and let known addresses past username lockout
- S2: 2b6a7f9 feat(security): add outbound URL policy and a connect-time guarded transport
- S2: f06f8f9 feat(security): enforce the outbound URL policy for every user-supplied URL
- S3: be7a64a feat(vault): support key rotation with MultiFernet and a rotate-vault-key command
- S3 docs: 3ec6ff7 docs(vault): document key rotation and pass the new settings through compose
- Tracker/gaps: see `git log --grep 'docs(odd)'` (a tracker commit cannot hold its own hash)

## Progress / verification
Baseline: 1635 passed on branch start (observed).
S1: RED observed (collection ImportError: SqliteIpLoginThrottle / domain.client_ip missing), then GREEN: 1671 passed. Decisions: counters in SQLite (migration 6: `login_ip_failures` one row per failure, `known_login_ips`), epoch-REAL timestamps, purge on write, blocked IP stops adding rows; success never clears the IP counter; known-address bypass of USERNAME lockout (address signed in for that username within 30 days; correct password required and still counted; never for password change; setting ADMIN_LOGIN_KNOWN_IP_DAYS=0 disables); XFF honoured only with TRUSTED_PROXY_COUNT>0, N-th from the right, fallback to peer on short/garbage chain; IPv6 keyed by /64. One existing test changed (password-change lockout test no longer asserts a known address cannot log in: that is now the designed bypass). `.env.example` is outside the tool permissions (read/edit denied): NOT updated, to be done by the user/parent.
S2: RED observed (collection ImportError OutboundUrlBlocked; settings tests failed on missing fields; enforcement tests hung on real connects to 169.254.169.254 before the guard existed, killed). Domain `domain/outbound.py` (pure) + `infrastructure/net/guard.py`: httpcore network backend (resolve once, validate ALL addresses, connect by validated IP; Host/SNI untouched; fallback to next validated address) replaces the pool of an `httpx.AsyncHTTPTransport` subclass (uses private `_pool`, covered by tests that fail if httpx changes), blocking twin `connect_guarded` for XML-RPC (via http.client `_create_connection`). Enforced in: RestHttpClient (also token_url / OIDC issuer requests: same client), REST and Odoo probes, OpenAPI loader (every connection incl. redirect hops; existing same-host/3-hop/5 MB rules kept), Odoo profile endpoints on jsonrpc/json2/xmlrpc. Not guarded on purpose: env ODOO_URL data API (operator-controlled; keeps proxy env behaviour). Guarded clients ignore HTTP(S)_PROXY env (trust_env=False). `OutboundUrlBlocked` subclasses RemoteUnavailable (runs fail as remote errors) and maps to 422 `outbound_url_blocked`; probes report a failed step. No existing test was edited for S2: four failed after the first wiring and were fixed in code (UnsupportedProtocol re-raised as httpx does; `verify` kept observable on the client). Total 1793 passed; ruff, format, mypy clean. e2e (`npx playwright test`): 3 passed. SUWE integration (`pytest -m integration`): 1 passed against the live fake.
S3: RED observed (collection ModuleNotFoundError `infrastructure.profiles.rotation`, then ImportError `conector_odoo.manage`; startup tests failed until the check existed, after a test-side fix for caplog being dropped by `configure_logging`). `FernetVault(key, previous_keys)` on MultiFernet (encrypt = primary only; `classify` current/outdated/undecryptable; `rotate`), `Settings.encryption_key_previous` (comma-separated SecretStr) and `build_vault`. `infrastructure/profiles/rotation.py`: `rotate_vault` = BEGIN IMMEDIATE, classify all, refuse with profile ids (no write) if any is unreadable, dry-run rolls back, only `outdated` rows are rewritten (idempotent), any error rolls back; `inspect_vault`; `check_vault_at_startup` logs counts and profile ids, never raises. CLI `python -m conector_odoo.manage check-vault | rotate-vault-key [--dry-run]` (no CLI existed; plain argparse module), exit 0/1/2, output without keys or secrets, does not create a missing DB. Settings error scrub also masks previous keys. docker-compose now forwards ENCRYPTION_KEY_PREVIOUS, TRUSTED_PROXY_COUNT, ADMIN_LOGIN_IP_*, ADMIN_LOGIN_KNOWN_IP_DAYS, OUTBOUND_* (compose only passes listed variables, so they would otherwise be unusable in Docker). README runbook (backup first, docker compose exec) added.
Final: `uv run pytest` 1822 passed (baseline 1635); ruff check, ruff format --check, mypy src clean. e2e 3 passed and SUWE integration 1 passed after S2 (not re-run after S3: no relevant change; the vault only gained keys). Frontend untouched. Route per task: single writer (this agent).
Not done / caveats: `.env.example` not updated (tool permissions deny it): add ADMIN_LOGIN_IP_MAX_FAILURES=20, ADMIN_LOGIN_IP_WINDOW_SECONDS=900, ADMIN_LOGIN_KNOWN_IP_DAYS=30, TRUSTED_PROXY_COUNT=0, OUTBOUND_URL_POLICY=default, OUTBOUND_ALLOWED_HOSTS=, ENCRYPTION_KEY_PREVIOUS= . No save-time URL validation of profiles (the policy applies when a request is made). Env-configured ODOO_URL is intentionally outside the policy. The guarded transport swaps `httpx.AsyncHTTPTransport._pool` (private attribute); tests fail loudly if httpx changes it. Compose changes not exercised with a real `docker compose up` in this task.
