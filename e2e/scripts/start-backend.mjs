// Starts the connector backend for the e2e run with a throw-away state:
// fresh SQLite DBs, a fresh Fernet vault key, a bootstrap admin, the scheduler off and the
// built frontend (frontend/dist) served at "/".
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const port = process.env.E2E_BACKEND_PORT ?? "8100";
const odooPort = process.env.E2E_ODOO_PORT ?? "8169";

// Playwright stops web servers with SIGKILL, so no exit hook can clean up after a run. A fixed,
// git-ignored directory that is wiped on every start gives the same freshness without leaks.
const stateDir = join(here, "..", ".state");
rmSync(stateDir, { recursive: true, force: true });
mkdirSync(stateDir, { recursive: true });
// A Fernet key is url-safe base64 of 32 random bytes.
const vaultKey = randomBytes(32).toString("base64url") + "=";

const env = {
  ...process.env,
  ODOO_URL: `http://127.0.0.1:${odooPort}`,
  ODOO_DB: "e2e",
  ODOO_USER: "admin",
  ODOO_API_KEY: "e2e-odoo-api-key-0123456789",
  WEBHOOK_SECRET: "e2e-webhook-secret-0123456789",
  ENCRYPTION_KEY: vaultKey,
  ADMIN_DB_PATH: join(stateDir, "admin.db"),
  IDEMPOTENCY_DB_PATH: join(stateDir, "idempotency.sqlite3"),
  FRONTEND_DIST_DIR: join(repoRoot, "frontend", "dist"),
  ADMIN_BOOTSTRAP_USER: process.env.E2E_ADMIN_USER ?? "e2e-admin",
  ADMIN_BOOTSTRAP_PASSWORD: process.env.E2E_ADMIN_PASSWORD ?? "e2e-admin-password-1",
  ADMIN_COOKIE_SECURE: "false",
  SYNC_SCHEDULER_ENABLED: "false",
  LOG_LEVEL: process.env.E2E_BACKEND_LOG_LEVEL ?? "ERROR",
};

const child = spawn(
  "uv",
  [
    "run",
    "uvicorn",
    "conector_odoo.main:create_app",
    "--factory",
    "--host",
    "127.0.0.1",
    "--port",
    port,
  ],
  { cwd: repoRoot, env, stdio: "inherit" },
);

function stop(signal) {
  child.kill(signal);
}
process.on("SIGINT", () => stop("SIGINT"));
process.on("SIGTERM", () => stop("SIGTERM"));
child.on("exit", (code) => process.exit(code ?? 0));
