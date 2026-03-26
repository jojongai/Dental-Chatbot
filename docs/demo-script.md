# Demo script

## Prerequisites

- Node.js 20+ and npm 10+
- Python 3.12+ and **uv** (see root `README.md`)
- Dependencies: `npm install` at repo root; `uv sync --group dev` in `apps/api`

## Steps

1. From the repo root, copy `.env.example` to `.env` and adjust if needed.
2. Run `npm install` at the repo root.
3. Run `uv sync --group dev` in `apps/api` (or `python3 -m uv sync --group dev`).
4. Run `npm run dev` — confirm Next.js on port 3000 and API on port 8000.
5. Open `http://localhost:3000` — page should load (includes a shadcn/ui button sample).
6. Open `http://localhost:8000/docs` — FastAPI Swagger UI should load.
7. Call `GET /health` — expect `{ "status": "ok", "service": "api", "database": "sqlite" }` when using the default SQLite URL.

Extend this script when chat and LLM features are added.
