#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}"
if command -v uv >/dev/null 2>&1; then
  exec uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
fi
if python3 -m uv --version >/dev/null 2>&1; then
  exec python3 -m uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
fi
PY=python3
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi
exec "$PY" -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
