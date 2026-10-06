# syntax=docker/dockerfile:1

# ---- frontend: build the admin SPA (Vite) ----
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend ./
RUN npm run build

# ---- builder: resolve and install locked, production-only dependencies with uv ----
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first (cached until pyproject.toml / uv.lock change).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Then the project itself.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime ----
FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# tini is PID 1: it forwards SIGTERM to uvicorn and reaps zombies.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown app:app /app/data

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src
COPY --from=frontend --chown=app:app /build/dist /app/frontend/dist

USER app

# Both SQLite databases (idempotency keys + admin DB) live on the volume. No secret is baked in:
# ODOO_*, WEBHOOK_SECRET, ENCRYPTION_KEY and ADMIN_BOOTSTRAP_* come from the environment.
ENV IDEMPOTENCY_DB_PATH=/app/data/idempotency.sqlite3 \
    ADMIN_DB_PATH=/app/data/admin.db \
    FRONTEND_DIST_DIR=/app/frontend/dist
VOLUME ["/app/data"]
EXPOSE 8000

# /livez checks the process only. /health answers 503 when Odoo is down and must not restart us.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=4)"]

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "conector_odoo.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
