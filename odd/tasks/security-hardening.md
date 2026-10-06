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
- [ ] S2 Outbound URL policy (domain policy, DNS resolve + connect-time pinning, default/strict, enforced at every outbound call, 422)
- [ ] S3 Vault key rotation (MultiFernet, ENCRYPTION_KEY_PREVIOUS, rotate command, startup check)
- [ ] Docs: README security section, env table, .env.example, architecture, close gaps in generic-connector-admin tracker

## Route log
- Tracker created before the first source write. All tasks: single writer (this agent, delegated by the parent orchestrator).

## Commits

## Progress / verification
Baseline: 1635 passed on branch start (observed).
S1: RED observed (collection ImportError: SqliteIpLoginThrottle / domain.client_ip missing), then GREEN: 1671 passed. Decisions: counters in SQLite (migration 6: `login_ip_failures` one row per failure, `known_login_ips`), epoch-REAL timestamps, purge on write, blocked IP stops adding rows; success never clears the IP counter; known-address bypass of USERNAME lockout (address signed in for that username within 30 days; correct password required and still counted; never for password change; setting ADMIN_LOGIN_KNOWN_IP_DAYS=0 disables); XFF honoured only with TRUSTED_PROXY_COUNT>0, N-th from the right, fallback to peer on short/garbage chain; IPv6 keyed by /64. One existing test changed (password-change lockout test no longer asserts a known address cannot log in: that is now the designed bypass). `.env.example` is outside the tool permissions (read/edit denied): NOT updated, to be done by the user/parent.
