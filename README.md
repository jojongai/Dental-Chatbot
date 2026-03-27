# Dental Chatbot

## Documentation

**→ Start here to see the Submission.md file** [`SUBMISSION_DOCUMENTATION.md`](SUBMISSION_DOCUMENTATION.md)

That document covers the working prototype, architecture, technology choices, design rationale, setup (including **venv + pip** or **uv**), repository organization, and how to test locally.

For deeper technical notes: [`docs/architecture.md`](docs/architecture.md) (system shape) and [`docs/flows.md`](docs/flows.md) (chat workflows and status). API-specific run notes: [`apps/api/README.md`](apps/api/README.md).

---

## Overview

This repository is a **monorepo** for a dental-office **assistant chatbot** prototype: patients use an SMS-style web UI to ask questions, book and manage appointments, register, and get help in urgent situations. A **FastAPI** backend owns business rules through a **workflow state machine**, calls **tools** (scheduling, patients, clinic data), and optionally uses **Google Gemini** for natural-language understanding. An **employee schedule** page reads the same API so front-desk views stay aligned with what the bot can book.

**Included:** Next.js frontend (`apps/chatbot-ui`), Python API (`apps/api`), shared types (`packages/shared-types`), prompts (`packages/prompts`), and markdown docs under `docs/`.

---

## Tech stack (summary)

| Area | Stack |
|------|--------|
| Frontend | Next.js, React, TypeScript, Tailwind CSS |
| Backend | FastAPI, Pydantic, SQLAlchemy |
| Database | SQLite locally (`apps/api/data/`); Postgres-ready via `DATABASE_URL` |
| LLM | Google Gemini (optional; `USE_LLM` + `GEMINI_API_KEY` in `.env`) |
| Tooling | npm workspaces + Turbo; Python deps via **uv** or **venv + pip** (see submission doc) |

---

## Prerequisites

- **Node.js** 20+ and **npm** 10+
- **Python** 3.12+

---

## Quick start

From the **repository root**:

```bash
npm install
cd apps/api && uv sync --group dev && cd ../..
cp .env.example .env
npm run dev
```

- Chat UI: [http://localhost:3000](http://localhost:3000)  
- Employee dashboard: [http://localhost:3000/employee](http://localhost:3000/employee)  
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

**Details:** optional database seed, environment variables, running without `uv`, and testing — all in [`SUBMISSION_DOCUMENTATION.md`](SUBMISSION_DOCUMENTATION.md) §6.

---

## Scripts (root)

| Command | Description |
|--------|-------------|
| `npm run dev` | Turbo: Next.js + API together |
| `npm run build` | Build workspaces |
| `npm run test` | Tests across workspaces |
| `npm run lint` | ESLint + Ruff |
| `npm run format` | Prettier |

---

## Run targets (optional)

- **Frontend only:** `npm run dev -- --filter=@dental-chatbot/chatbot-ui` or `cd apps/chatbot-ui && npm run dev`
- **API only:** `npm run dev -- --filter=@dental-chatbot/api` or `cd apps/api && npm run dev`

---

## Repository layout

```
apps/chatbot-ui      # Next.js — SMS demo, employee schedule
apps/api             # FastAPI app, models, tests, seed.py
packages/shared-types
packages/prompts
docs/                # Architecture, flows
SUBMISSION_DOCUMENTATION.md   # Full project documentation (see top)
.env.example         # Copy to .env for local configuration
```