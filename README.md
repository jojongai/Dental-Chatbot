# Dental Chatbot

Monorepo for a dental-office assistant chatbot: **Next.js** chatbot UI (`apps/chatbot-ui`), **FastAPI** backend (`apps/api`), shared contracts (`packages/shared-types`), and prompts (`packages/prompts`).

## Tech stack (prototype)

| Layer              | Choices                                        | Notes                                                                                                                                      |
| ------------------ | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| **Frontend**       | Next.js, React, TypeScript, Tailwind CSS       | Fast to ship; deploy to **Vercel**.                                                                                                        |
| **UI**             | **shadcn/ui** (Base UI + Radix-style patterns) | Demo-friendly, accessible primitives via `npx shadcn`.                                                                                     |
| **Backend**        | **FastAPI**, **Pydantic**                      | REST + validation; LLM orchestration stays in Python.                                                                                      |
| **Persistence**    | **SQLAlchemy**                                 | **SQLite** file under `apps/api/data/` for local/demo; switch `DATABASE_URL` to **Postgres** (e.g. **Supabase**) for production-like runs. |
| **Python tooling** | **[uv](https://docs.astral.sh/uv/)**           | Lockfile + fast installs (`uv.lock` in `apps/api`). Poetry is a fine alternative; this repo standardizes on uv.                            |

See `docs/architecture.md` for boundaries and data flow.
See `docs/flows.md` for a full list of supported chat flows and their implementation status.

## Prerequisites

- **Node.js** 20+ and **npm** 10+
- **Python** 3.12+
- **[uv](https://docs.astral.sh/uv/)** for the API (install: `pip install uv` or the [official installer](https://docs.astral.sh/uv/getting-started/installation/))

## Setup

1. Clone the repo and install Node dependencies from the **repository root**:

   ```bash
   npm install
   ```

2. Install Python dependencies for the API with **uv**:

   ```bash
   cd apps/api
   uv sync --group dev
   cd ../..
   ```

   If `uv` is not on your `PATH`, use `python3 -m uv sync --group dev` from `apps/api`.

3. Copy environment defaults:

   ```bash
   cp .env.example .env
   ```

## Scripts (root)

| Command                | Description                                                      |
| ---------------------- | ---------------------------------------------------------------- |
| `npm run dev`          | Runs **Turbo** `dev` — Next.js and FastAPI together (see below). |
| `npm run build`        | Builds workspaces (Next.js + `shared-types`).                    |
| `npm run test`         | Runs tests in all workspaces.                                    |
| `npm run lint`         | ESLint (TS/JS) + Ruff (Python).                                  |
| `npm run format`       | Prettier for Markdown/TS/JS.                                     |
| `npm run format:check` | Check formatting only.                                           |

## Run locally

- **Frontend only** (from root):

  ```bash
  npm run dev -- --filter=@dental-chatbot/chatbot-ui
  ```

  Or: `cd apps/chatbot-ui && npm run dev` → [http://localhost:3000](http://localhost:3000) (employee dashboard: [http://localhost:3000/employee](http://localhost:3000/employee))

- **Backend only** (with uv sync done in `apps/api`):

  ```bash
  npm run dev -- --filter=@dental-chatbot/api
  ```

  Or: `cd apps/api && npm run dev` → [http://localhost:8000/docs](http://localhost:8000/docs)

- **Both** (default):

  ```bash
  npm run dev
  ```

## Layout

```
apps/chatbot-ui   # Next.js + Tailwind + shadcn/ui — SMS demo (`/`) + employee schedule (`/employee`, mock data)
apps/api          # FastAPI + Pydantic + SQLAlchemy + uv
packages/prompts  # System prompts & fragments
packages/shared-types  # Zod schemas / TS types (mirror in Pydantic)
docs/             # Architecture & planning
infra/seed/       # Seed data (placeholder)
```

See `docs/demo-script.md` for a short smoke checklist.
