#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}"
if command -v uv >/dev/null 2>&1; then
  uv run ruff check .
  uv run ruff format --check .
  exit 0
fi
if python3 -m uv --version >/dev/null 2>&1; then
  python3 -m uv run ruff check .
  python3 -m uv run ruff format --check .
  exit 0
fi
PY=python3
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi
"$PY" -m ruff check .
"$PY" -m ruff format --check .
