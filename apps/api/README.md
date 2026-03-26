# Dental Chatbot API

FastAPI service with **Pydantic** validation and **SQLAlchemy** persistence.

## Dependencies (uv)

This project uses **[uv](https://docs.astral.sh/uv/)** for dependency management and virtualenvs.

```bash
cd apps/api
uv sync --group dev
```

The API scripts set `UV_CACHE_DIR` to `apps/api/.uv-cache` (gitignored) so `uv` works in sandboxes and CI without writing to the global cache.

Run the server (from `apps/api`):

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Or from the monorepo root: `npm run dev -- --filter=@dental-chatbot/api`.

## Database

- **Local / demo:** SQLite file under `data/` (default `DATABASE_URL=sqlite:///./data/app.db`).
- **Production-like:** set `DATABASE_URL` to a Postgres URL (e.g. Supabase), using `postgresql+psycopg://...` with SQLAlchemy.

See the root `.env.example` for variables.
