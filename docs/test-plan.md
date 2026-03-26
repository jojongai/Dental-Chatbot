# Test plan

## Automated

| Layer    | Tool                                         | Scope                                     |
| -------- | -------------------------------------------- | ----------------------------------------- |
| API      | `pytest` + FastAPI `TestClient`              | Route handlers, validation, auth (later). |
| Web      | To be chosen (e.g. Vitest + Testing Library) | Components, hooks.                        |
| Monorepo | `turbo test`                                 | Runs workspace `test` scripts.            |

## Manual / demo

- Smoke: health endpoints (`GET /health`), web home loads.
- Chat flows: covered in `demo-script.md` once features exist.

## Exit criteria (skeleton)

- `turbo test` completes (API has a minimal health test; web may echo “no tests yet”).
- Lint passes for configured JS/TS and Python paths.
