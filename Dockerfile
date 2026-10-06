# syntax=docker/dockerfile:1

# ---- builder: resolve and install locked, production-only dependencies with uv ----
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first (cached until pyproject.toml / uv.lock change).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Then the project itself.
COPY src ./src
RUN uv sync --frozen --no-dev

# ---- runtime ----
FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data \
    && chown app:app /app/data

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src

USER app

# SQLite files (idempotency keys, webhook events) live here; mount a volume to keep them.
ENV IDEMPOTENCY_DB_PATH=/app/data/idempotency.sqlite3
VOLUME ["/app/data"]
EXPOSE 8000

# /health answers 503 when Odoo is unreachable, which marks the container unhealthy on purpose.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["uvicorn", "conector_odoo.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
