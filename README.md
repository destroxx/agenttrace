# AgentTrace

Record-and-replay regression testing for AI agents.

## The problem

An AI agent is only partly its own code. The rest is the tools it calls —
search, a payments API, your own database — and those live outside the process
and change without warning. So the obvious way to check that a prompt change or
a model upgrade did not break anything, re-running yesterday's scenarios, means
calling those real systems again: slow, expensive, and unsafe once a tool can
refund money or send mail. Worse, it does not even answer the question, because
the tools return different data than they did yesterday, so a diff in the output
tells you nothing about whether the agent got worse. AgentTrace records what the
tools actually returned during a real run, so a later version of the agent can
be replayed against that recording instead of against production.

## How it works

```
  Record  ──────▶  Save  ──────▶  Replay  ──────▶  Compare
  the SDK wraps    one request    re-run a new     did the new
  your agent and   per finished   agent against    agent behave
  its tools; the   run, stored    the recording,   differently?
  whole run is     in one         serving the      surface the
  buffered         transaction    recorded tool    differences
  in memory                       results back
                                  instead of
                                  calling the
                                  real tools

  ✅ implemented   ✅ implemented  ⬜ planned       ⬜ planned
```

**Record** and **Save** work today. **Replay** and **Compare** are not built —
there is no replay engine, no tool mocking and no comparison logic yet.

## Status

| | Milestone | What it means |
| --- | --- | --- |
| ✅ | Foundation | Monorepo, FastAPI service, Postgres via Compose, Next.js app |
| ✅ | Data model & REST API | `Project ──< Run ──< Event`, 11 endpoints, Alembic migrations |
| ✅ | Frozen terminal runs | A finished run rejects new events; row lock serialises close vs. append |
| ✅ | One-request ingest | A whole finished run and its trace in a single transaction |
| ✅ | Python SDK recorder | Async/sync tracing, `@tracer.tool`, end-of-run upload, record-time snapshots |
| ⬜ | Replay | Re-run an agent with recorded tool results served back to it |
| ⬜ | Compare & regression suites | Diff a replay against its recording; run suites in CI |
| ⬜ | Dashboard | `apps/web` is a single page showing API health |
| ⬜ | Auth, billing, queues, deployment | Not started; the SDK sends an API key the API does not check |

## Key design decisions

Each links to the reasoning in [`docs/architecture.md`](docs/architecture.md).

- **Ingest is one transaction, keyed by a client-generated run id.** A retried
  upload conflicts instead of duplicating, and a half-stored trace — which
  replay would read as an agent that legitimately stopped early — is
  impossible. [Details](docs/architecture.md#design-decisions)
- **`call_id` pairs a call with its answer.** `sequence` gives order, not which
  response belongs to which call, so parallel tool calls need an explicit
  pairing key. [Details](docs/architecture.md#design-decisions)
- **Recordings are snapshotted at record time.** Upload happens when the run
  ends, so an event holding a live reference would record whatever the agent
  did to that value afterwards. [Details](docs/architecture.md#sdk)
- **The SDK never breaks the host application.** Tool results and exceptions
  pass through unchanged; recording and upload failures are logged and
  swallowed. [Details](docs/architecture.md#sdk)
- **The SDK has no runtime dependencies.** It is imported into someone else's
  agent process, so it must not constrain their dependency tree — the transport
  is `urllib`. [Details](docs/architecture.md#sdk)
- **Terminal runs are frozen.** A `completed`/`failed` run rejects new events,
  and closing and appending take a row lock so they cannot interleave.
  [Details](docs/architecture.md#design-decisions)

---

## Quickstart

Prerequisites: Python 3.12+, Node.js 20+, Docker with Compose.

### 1. Start PostgreSQL

```bash
cp .env.example .env
```

Set `POSTGRES_PASSWORD` in `.env` to a generated value (`openssl rand -hex 16`).
No credential has a default anywhere in the code — Compose and the API both
refuse to start without one.

```bash
docker compose up -d
docker compose ps          # wait for "(healthy)"
```

### 2. Configure the API

```bash
cp apps/api/.env.example apps/api/.env
```

Set `POSTGRES_PASSWORD` there to the **same value** as the root `.env`.
Alternatively set a single `DATABASE_URL`, which overrides the discrete
`POSTGRES_*` settings:

```env
DATABASE_URL=postgresql+psycopg://agenttrace:secret@localhost:5432/agenttrace
```

The stack is async end to end, so a DSN naming a sync driver (`postgresql://`,
`postgresql+psycopg://`) is rewritten onto `asyncpg` automatically.

### 3. Install and migrate

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e "apps/api[dev]" -e "packages/python-sdk[dev]"

cd apps/api
alembic upgrade head
```

### 4. Start the API

```bash
cd apps/api
uvicorn app.main:app --reload
```

- Health: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>

### 5. Record your first run

With the API running, in a second shell:

```bash
source .venv/bin/activate

PROJECT=$(curl -s -X POST localhost:8000/api/v1/projects \
  -H 'content-type: application/json' \
  -d '{"name":"Demo"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
export AGENTTRACE_PROJECT_ID=$PROJECT

python examples/async_support_agent.py
```

The demo agent is scripted — no LLM, no API key. It calls four tools, two of
them in parallel, and prints the trace it uploaded:

```
trace id:  28241f16-a1da-4ab5-b339-58a54950c9db
status:    completed
events:    14
uploaded:  True
```

Read the recording back, always in sequence order:

```bash
curl -s localhost:8000/api/v1/runs/$TRACE_ID
curl -s localhost:8000/api/v1/runs/$TRACE_ID/events
```

The two parallel `get_order` calls both open (sequences 3 and 4) before either
answers (5 and 6); each response carries its own call's `call_id`, which is what
lets them be paired back up.

Stop the API and run the example again: the agent finishes normally, logs one
warning, and reports `uploaded: False`. Recording is never allowed to break the
application it is recording.

### 6. Start the web app (optional)

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

It is a single page showing API health. There is no dashboard yet.

---

## SDK usage

The SDK records a whole run in memory and uploads it in one request when the
run ends.

```python
import asyncio
from agenttrace import AgentTracer

tracer = AgentTracer()  # reads the AGENTTRACE_* environment


@tracer.tool
async def get_order(order_id: str) -> dict:
    return {"id": order_id, "status": "shipped"}


async def main() -> None:
    async with tracer.trace(
        "support-agent",
        input={"message": "Where is my order?"},
        agent_version="v1.0.0",
        user_id="u-1",          # anything else becomes run metadata
    ) as trace:
        order = await get_order("A-1")
        trace.set_output({"message": f"Your order is {order['status']}."})

    print(trace.id, trace.status, len(trace.events), trace.uploaded)


asyncio.run(main())
```

`with tracer.trace(...)` works the same way for a synchronous agent, and
`@tracer.tool` decorates sync and async functions alike.
`tracer.record_tool_call(name, arguments, response)` is there for tools you
cannot decorate.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTTRACE_API_URL` | `http://localhost:8000` | Where the API lives |
| `AGENTTRACE_API_KEY` | _unset_ | Sent as a bearer token; **the API does not check it yet** |
| `AGENTTRACE_PROJECT_ID` | _unset_ | The project runs are uploaded to |
| `AGENTTRACE_TIMEOUT` | `5` | Seconds to wait for one upload |

**Uploading is opt-in**: without `AGENTTRACE_PROJECT_ID` the SDK keeps traces in
memory and never opens a socket, so it is safe to import in tests and offline.

Full SDK documentation, including known limitations, is in
[`packages/python-sdk/README.md`](packages/python-sdk/README.md).

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
| POST | `/api/v1/projects/{project_id}/runs/ingest` | Upload one finished run and its whole trace |
| GET | `/api/v1/projects/{project_id}/runs` | List a project's runs (paginated) |
| GET | `/api/v1/runs/{run_id}` | Get a run |
| POST | `/api/v1/runs/{run_id}/complete` | Record output and final status |
| POST | `/api/v1/runs/{run_id}/events` | Append an event |
| GET | `/api/v1/runs/{run_id}/events` | List events ordered by `sequence` |

Errors: `404` for a missing project or run; `409` for a duplicate event
sequence, a run that has already finished, an event posted to a finished run, or
re-uploading a run id that is already stored; `422` for a malformed body or a
path id that is not a UUID.

Paginated endpoints take `?page=1&page_size=20` (`page_size` caps at 100) and
return `{"items": [...], "total": n, "page": n, "page_size": n}`.

The SDK uses `ingest`. The step-by-step path exists for recorders that cannot
buffer a whole run:

```bash
API=http://localhost:8000/api/v1
RUN=d8686012-6e56-483f-bbfc-c69c22d91f52   # from POST /projects/$PROJECT/runs

curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":1,"event_type":"agent_start"}'
curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":2,"event_type":"tool_call","call_id":"call_abc123",
       "tool_name":"get_order","arguments":{"order_id":"12345"}}'
curl -s -X POST $API/runs/$RUN/events -H 'content-type: application/json' \
  -d '{"sequence":3,"event_type":"tool_response","call_id":"call_abc123",
       "tool_name":"get_order","response":{"status":"in_transit"},"duration_ms":42}'
curl -s -X POST $API/runs/$RUN/complete -H 'content-type: application/json' \
  -d '{"output":{"message":"Arriving tomorrow."},"status":"completed"}'
```

Order of insertion does not matter — reads are always ordered by `sequence`. A
finished run answers `409` rather than overwriting its recorded output, and two
events cannot claim the same `sequence` within a run.

Optionally load one realistic trace to poke at:

```bash
cd apps/api && python -m scripts.seed_dev_data
```

It is not idempotent — each run creates a new project.

## Project structure

```
agenttrace/
├── apps/
│   ├── api/              FastAPI service, SQLAlchemy models, Alembic
│   └── web/              Next.js + TypeScript + Tailwind + shadcn/ui
├── packages/
│   └── python-sdk/       `agenttrace` SDK with the AgentTracer class
├── examples/             Runnable SDK examples
├── docs/                 Architecture notes and trade-offs
└── docker-compose.yml    Local PostgreSQL
```

Inside `apps/api`, dependencies point inward and nothing depends on transport:
routes (`app/api/`) carry no business logic, services (`app/services/`) never
import FastAPI and raise only `NotFoundError`/`ConflictError`, and
`app/config.py` is the only module that reads the environment.

## Running the tests

```bash
# API — creates and migrates its own `agenttrace_test` database
cd apps/api && pytest

# same, but fail instead of skip when PostgreSQL is unreachable (use in CI)
cd apps/api && RUN_INTEGRATION_TESTS=1 pytest

# SDK
cd packages/python-sdk && pytest

# lint
ruff check apps/api packages/python-sdk examples

# web — build before tsc: `npx tsc --noEmit` alone fails on a clean checkout,
# because types like LayoutProps are generated by Next into .next/types/,
# which tsconfig.json includes.
cd apps/web && npm run lint && npm run build && npx tsc --noEmit
```

Currently 77 API tests and 40 SDK tests. The API suite owns a separate database
and rolls back every test, so running it never touches development data.

Migrations are reversible; the round trip is worth checking after a schema
change:

```bash
cd apps/api
alembic upgrade head && alembic downgrade base && alembic upgrade head
alembic check          # "No new upgrade operations detected."
```

## Troubleshooting

**The API cannot authenticate, but `docker compose ps` says `(healthy)`.**
`POSTGRES_PASSWORD` is only applied when the data volume is first created, so
changing it in `.env` afterwards leaves the database expecting the old one. To
adopt the new password, recreate the volume — **this deletes all local data**:

```bash
docker compose down -v && docker compose up -d
```

`(healthy)` does not prove password authentication works: the healthcheck runs
`pg_isready` over the container's local socket, where `pg_hba.conf` uses
`trust`. Only a TCP connection — which is how the API connects — exercises
authentication.

**`pytest -v` prints no per-test list.** `pyproject.toml` sets `addopts = "-q"`,
which cancels it. Use `pytest -o addopts="" -v`.

## Known limitations

The deliberate trade-offs — end-of-run upload losing a run to a hard kill, the
per-socket upload timeout, unrecorded tools in raw threads, and more — are
listed in
[`docs/architecture.md`](docs/architecture.md#known-limitations-and-deliberate-trade-offs).

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
| `packages/python-sdk/.env` | SDK consumers | `AGENTTRACE_API_URL`, `AGENTTRACE_API_KEY`, `AGENTTRACE_PROJECT_ID`, `AGENTTRACE_TIMEOUT` |

Every file has a committed `.env.example`; real `.env` files are gitignored.
