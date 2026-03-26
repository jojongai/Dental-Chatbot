# Implementation plan

## Phase 0 — Skeleton (current)

- [x] Monorepo layout (`apps/`, `packages/`, `docs/`, `infra/`)
- [x] Next.js + TypeScript + Tailwind in `apps/web`; **shadcn/ui** initialized for UI primitives
- [x] FastAPI + Pydantic in `apps/api`; **SQLAlchemy** wired with **SQLite** default and Postgres-ready `DATABASE_URL`
- [x] Python dependencies managed with **uv** (`uv.lock` in `apps/api`)
- [x] Shared types package and prompts package placeholders
- [x] Root scripts: `dev`, `build`, `test`, `lint`, formatting

## Next phases (outline)

1. **Chat API**: streaming responses, session/thread model, error handling.
2. **UI**: chat layout, message list, input, loading states.
3. **Observability**: structured logging, basic metrics.
4. **Quality**: integration tests, contract tests for API ↔ shared-types alignment.

Update this document as scope becomes concrete.
