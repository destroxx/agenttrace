# AgentTrace API

FastAPI service backing AgentTrace. See the [repository README](../../README.md)
for full local setup.

## Layout

| Path | Responsibility |
| --- | --- |
| `app/config.py` | Environment-driven settings; the only module that reads the environment |
| `app/db/` | Declarative base, engine, session lifecycle |
| `app/models/` | SQLAlchemy models — how rows are stored |
| `app/schemas/` | Pydantic schemas — what the API accepts and returns |
| `app/services/` | Business logic; raises domain errors, never imports FastAPI |
| `app/api/v1/` | Versioned REST routers |
| `app/api/routes/` | Unversioned operational routes (`/health`) |
| `app/migrations/` | Alembic environment and revisions |
| `scripts/` | Developer utilities (`seed_dev_data`) |
| `tests/` | Pytest suite |

## Run

```bash
cp .env.example .env          # then set POSTGRES_PASSWORD
alembic upgrade head
uvicorn app.main:app --reload
```

Interactive docs: <http://localhost:8000/docs>

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | API and database health; `503` when degraded |
| POST | `/api/v1/projects` | Create a project |
| GET | `/api/v1/projects` | List projects (paginated) |
| GET | `/api/v1/projects/{project_id}` | Get a project |
| POST | `/api/v1/projects/{project_id}/runs` | Start a run |
| GET | `/api/v1/projects/{project_id}/runs` | List a project's runs (paginated) |
| GET | `/api/v1/runs/{run_id}` | Get a run |
| POST | `/api/v1/runs/{run_id}/complete` | Finish a run |
| POST | `/api/v1/runs/{run_id}/events` | Append an event |
| GET | `/api/v1/runs/{run_id}/events` | List events, ordered by `sequence` |

## Tests

```bash
pytest                          # skips database tests if Postgres is down
RUN_INTEGRATION_TESTS=1 pytest  # fails instead of skipping — use this in CI
```

The suite owns a separate database (`POSTGRES_TEST_DB`, default
`agenttrace_test`). It creates that database, migrates it with the project's
own Alembic revisions, and runs each test inside a transaction that is rolled
back afterwards. Development data is never touched.

## Seed data

```bash
python -m scripts.seed_dev_data
```

Writes one project, one run, three events, and completes the run.
