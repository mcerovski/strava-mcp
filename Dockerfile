# syntax=docker/dockerfile:1

# ---- builder: resolve deps + install the project into a venv with uv ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached layer) from the frozen lockfile, without the
# project itself so this layer only busts when pyproject.toml / uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now install the project (README.md is referenced by the wheel build).
COPY README.md ./
COPY strava_mcp ./strava_mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime: slim image carrying only the venv + source ----
FROM python:3.12-slim-bookworm AS runtime

# Non-root user; /data is pre-created so a fresh named volume inherits its
# ownership on first mount (Docker copies the mountpoint's uid/gid).
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home app \
    && mkdir -p /data \
    && chown -R app:app /data

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app strava_mcp ./strava_mcp
COPY --chown=app:app README.md pyproject.toml ./

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Persist everything the app writes under the shared /data volume.
    STRAVA_DB_PATH=/data/db/strava.db \
    STRAVA_LOG_PATH=/data/logs/strava-mcp.log \
    STRAVA_AUDIT_PATH=/data/logs/audit.log

USER app
VOLUME ["/data"]

# Default to the MCP server + sync worker; compose overrides this for the
# dashboard and the one-off auth command.
ENTRYPOINT ["strava-mcp"]
CMD ["serve"]
