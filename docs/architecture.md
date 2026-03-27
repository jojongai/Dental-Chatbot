# Architecture

## Overview

The **dental-chatbot** monorepo separates the user-facing web app, the HTTP API, and shared contracts so chat features can evolve without blurring boundaries. The stack favors **speed** and **maintainability** for a prototype.

## Components

| Area                    | Role                                                                                                            |
| ----------------------- | --------------------------------------------------------------------------------------------------------------- |
| `apps/chatbot-ui`       | **Next.js + React + TypeScript + Tailwind CSS + shadcn/ui**: SMS chatbot UI (`/`), employee schedule dashboard (`/employee`, mock data), Vercel deployment. |
| `apps/api`              | **FastAPI + Pydantic**: REST (`/chat`, `/v1/employee/schedule` for the employee calendar, tools, validation).   |
| `packages/shared-types` | **Zod** schemas / TypeScript types mirrored loosely in Python (**Pydantic**) for request/response shapes.       |
| `packages/prompts`      | System prompts and reusable prompt fragments (Markdown or structured text).                                     |
| `infra/seed`            | Seed data and scripts for local or demo environments.                                                           |

## Persistence

- **Local / demo:** **SQLite** via SQLAlchemy (default `DATABASE_URL` points at a file under `apps/api/data/`). Lowest friction for development and demos.
- **Production-like:** set `DATABASE_URL` to a **PostgreSQL** URL (e.g. **Supabase**). Use the SQLAlchemy URL form `postgresql+psycopg://...` with the installed `psycopg` driver.

Application code should go through a single SQLAlchemy session / repository layer so swapping SQLite ↔ Postgres is mostly configuration.

## Data flow (target)

1. Browser talks to **Next.js** (SSR/CSR as appropriate).
2. Next.js calls **FastAPI** over HTTP (same origin or configured CORS).
3. API loads prompts from `packages/prompts`, validates I/O with **Pydantic** models aligned with **shared-types**, and persists via **SQLAlchemy**.

## Conventions

- Environment-specific values live in `.env` (see root `.env.example`); never commit secrets.
- Prefer adding shared DTOs in `packages/shared-types` before duplicating shapes in FE/BE.
