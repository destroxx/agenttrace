# AgentTrace

Record-and-replay regression testing for AI agents.

AgentTrace records real AI-agent executions — including tool calls and their
responses — so that a later version of the agent can be replayed against them
without calling the real external tools.

> **Milestone status.** The data model and REST API are in place: projects,
> runs and events can be recorded and read back. **Replay, evaluation,
> semantic comparison, authentication, billing, queues and deployment are not
> implemented.** See [`docs/architecture.md`](docs/architecture.md).

## Layout

```
agenttrace/
├── apps/
│   ├── api/              FastAPI service, SQLAlchemy models, Alembic
│   └── web/              Next.js + TypeScript + Tailwind + shadcn/ui
├── packages/
│   └── python-sdk/       `agenttrace` SDK with the AgentTracer class
├── examples/             Runnable SDK examples
├── docs/                 Architecture notes
└── docker-compose.yml    Local PostgreSQL
```

## Prerequisites

- Python 3.12+
- Node.js 20+
- Docker (with Compose)

---

## 1. Start PostgreSQL

```bash
cp .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env` to a generated value:

```bash
openssl rand -hex 16
```

No credential has a default anywhere in the code — Compose and the API both
refuse to start without one. Then:

```bash
docker compose up -d
docker compose ps          # wait for "(healthy)"
```

## 2. Configure the API

```bash
cp apps/api/.env.example apps/api/.env
```

Set `POSTGRES_PASSWORD` there to the **same value** as the root `.env`.

Alternatively set a single `DATABASE_URL` in `apps/api/.env`, which overrides
the discrete `POSTGRES_*` settings:

```env
DATABASE_URL=postgresql+psycopg://agenttrace:secret@localhost:5432/agenttrace
```

The stack is async end to end, so a DSN naming a sync driver (`postgresql://`,
`postgresql+psycopg://`) is rewritten onto `asyncpg` automatically.

## 3. Install and migrate

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e "apps/api[dev]" -e "packages/python-sdk[dev]"

cd apps/api
alembic upgrade head
```

Other migration commands:

```bash
alembic current                                  # show applied revision
alembic downgrade -1                             # roll one back
alembic revision --autogenerate -m "add x"       # create a revision
```

## 4. Start the API

```bash
cd apps/api
uvicorn app.main:app --reload
```

- Health: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>

Optionally load one realistic trace to poke at:

```bash
cd apps/api && python -m scripts.seed_dev_data
```

## 5. Start the web app

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

## 6. Run the tests

```bash
# API — creates and migrates its own `agenttrace_test` database
cd apps/api && pytest

# same, but fail instead of skip when PostgreSQL is unreachable (use in CI)
cd apps/api && RUN_INTEGRATION_TESTS=1 pytest

# SDK
cd packages/python-sdk && pytest

# lint
ruff check apps/api packages/python-sdk examples

# web
cd apps/web && npm run lint && npx tsc --noEmit && npm run build
```

The API suite owns a separate database and rolls back every test, so running
it never touches development data.

---

## API

All endpoints are under `/api/v1`, except `/health`, which is unversioned
because it describes the process rather than the API contract.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | API and database health; `503` when degraded |
| POST | `/api/v1/projects` | Create a project |
| GET | `/api/v1/projects` | List projects (paginated) |
| GET | `/api/v1/projects/{project_id}` | Get a project |
| POST | `/api/v1/projects/{project_id}/runs` | Start a run (status `running`) |
| GET | `/api/v1/projects/{project_id}/runs` | List a project's runs (paginated) |
| GET | `/api/v1/runs/{run_id}` | Get a run |
| POST | `/api/v1/runs/{run_id}/complete` | Record output and final status |
| POST | `/api/v1/runs/{run_id}/events` | Append an event |
| GET | `/api/v1/runs/{run_id}/events` | List events ordered by `sequence` |

Errors: `404` for a missing project or run, `409` for a duplicate event
sequence, for a run that has already finished, or for an event posted to a
finished run, `422` for a malformed body or a path id that is not a UUID.

Paginated endpoints take `?page=1&page_size=20` (`page_size` caps at 100) and
return `{"items": [...], "total": n, "page": n, "page_size": n}`.

### Example workflow

```bash
API=http://localhost:8000/api/v1

# 1. Create a project
curl -s -X POST $API/projects \
  -H 'content-type: application/json' \
  -d '{"name":"Customer Support Agent","description":"Regression tests for our support agent"}'
# -> {"id":"9ffb2534-...","name":"Customer Support Agent",...}

PROJECT=9ffb2534-e76d-46b1-a5d4-8335bcb2fff4

# 2. Start a run — it always begins as "running"
curl -s -X POST $API/projects/$PROJECT/runs \
  -H 'content-type: application/json' \
  -d '{"agent_name":"support-agent","agent_version":"v1.2.0","input":{"message":"Where is my order?"}}'
# -> {"id":"d8686012-...","status":"running","completed_at":null,...}

RUN=d8686012-6e56-483f-bbfc-c69c22d91f52

# 3. Record what the agent did. Order of insertion does not matter.
curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":1,"event_type":"agent_start"}'
curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":2,"event_type":"tool_call","tool_name":"get_order","arguments":{"order_id":"12345"}}'
curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":3,"event_type":"tool_response","tool_name":"get_order","response":{"status":"in_transit","eta":"2026-09-19"},"duration_ms":42}'
curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":4,"event_type":"agent_end"}'

# 4. Finish the run
curl -s -X POST $API/runs/$RUN/complete \
  -H 'content-type: application/json' \
  -d '{"output":{"message":"Your order is arriving tomorrow."},"status":"completed"}'
# -> {"status":"completed","completed_at":"2026-09-18T18:09:38.195334Z",...}

# 5. Read the trace back, always in sequence order
curl -s $API/runs/$RUN/events
curl -s $API/runs/$RUN
```

A run that has already finished answers `409` rather than overwriting its
recorded output, and two events cannot claim the same `sequence` within a run.
A finished run also rejects new events with `409`: once closed, a trace is a
frozen recording.

---

## Troubleshooting

**The API cannot authenticate, but `docker compose ps` says `(healthy)`.**
`POSTGRES_PASSWORD` is only applied when the data volume is first created, so
changing it in `.env` afterwards leaves the database expecting the old one. To
adopt the new password, recreate the volume — **this deletes all local data**:

```bash
docker compose down -v && docker compose up -d
```

Note that `(healthy)` does not prove password authentication works. The
healthcheck runs `pg_isready` over the container's local socket, where
`pg_hba.conf` uses `trust`, so it never checks a password. Only a TCP
connection — which is how the API connects — exercises authentication.

---

## SDK usage

```python
from agenttrace import AgentTracer

tracer = AgentTracer()  # reads AGENTTRACE_API_URL / AGENTTRACE_API_KEY

with tracer.trace("checkout-agent", user="u-1") as trace:
    tracer.record_tool_call("search", {"q": "shoes"}, response=["a", "b"])

print(len(trace.tool_calls))  # 1
```

Traces are held in memory; uploading them to the API is a later milestone.
A runnable version is in [`examples/record_tool_calls.py`](examples/record_tool_calls.py).

## Shutting down

```bash
docker compose down          # stop PostgreSQL, keep data
docker compose down -v       # stop and delete the data volume
```

## Configuration reference

| File | Consumed by | Notes |
| --- | --- | --- |
| `.env` | `docker-compose.yml` | Postgres database, user, password, host port |
| `apps/api/.env` | FastAPI, Alembic, tests | `DATABASE_URL` or `POSTGRES_*`, CORS allowlist |
| `apps/web/.env.local` | Next.js | `NEXT_PUBLIC_API_URL` (public, never secret) |
| `packages/python-sdk/.env` | SDK consumers | `AGENTTRACE_API_URL`, `AGENTTRACE_API_KEY` |

Every file has a committed `.env.example`; real `.env` files are gitignored.
