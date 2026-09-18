# AgentTrace API

FastAPI service backing AgentTrace. See the [repository README](../../README.md)
for the full local setup.

## Layout

| Path | Responsibility |
| --- | --- |
| `app/config.py` | Environment-driven settings |
| `app/db/` | Declarative base, engine, session lifecycle |
| `app/services/` | Business logic |
| `app/schemas/` | Public request/response contracts |
| `app/api/` | HTTP transport: routers and dependencies |
| `app/migrations/` | Alembic environment and revisions |
| `tests/` | Pytest suite |

## Run

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD
uvicorn app.main:app --reload
```

## Endpoints

- `GET /health` — reports API and database health; `503` when the database is
  unreachable.
