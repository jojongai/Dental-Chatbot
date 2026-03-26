#!/usr/bin/env bash
# Runs `alembic upgrade head` for Postgres deployments.
# For SQLite (local dev) tables are created via init_db() on startup.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}"
REVISION="${1:-head}"
if command -v uv >/dev/null 2>&1; then
  exec uv run alembic upgrade "$REVISION"
fi
if python3 -m uv --version >/dev/null 2>&1; then
  exec python3 -m uv run alembic upgrade "$REVISION"
fi
PY=python3
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi
exec "$PY" -m alembic upgrade "$REVISION"
