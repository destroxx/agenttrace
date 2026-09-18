# AgentTrace

Record-and-replay regression testing for AI agents.

AgentTrace records real AI-agent executions — including tool calls and their
responses — so that a later version of the agent can be replayed against them
without calling the real external tools.

> **Milestone status.** This repository currently contains the project
> foundation only. Replay, evaluation, semantic comparison, CI/CD integration,
> billing, authentication and AI features are **not** implemented. See
> [`docs/architecture.md`](docs/architecture.md).

## Layout

```
agenttrace/
├── apps/
│   ├── api/              FastAPI service (GET /health)
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

## Setup

### 1. Configure the environment

```bash
cp .env.example .env
```

Then set `POSTGRES_PASSWORD` in `.env` to a generated value:

```bash
openssl rand -hex 16
```

There is no default password anywhere in the code — Compose and the API both
refuse to start without one.

### 2. Start PostgreSQL

```bash
docker compose up -d
docker compose ps          # wait for "(healthy)"
```

### 3. Install the Python workspace

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e "apps/api[dev]" -e "packages/python-sdk[dev]"
```

### 4. Configure and start the API

```bash
cp apps/api/.env.example apps/api/.env
```

Set `POSTGRES_PASSWORD` in `apps/api/.env` to the **same value** as the root
`.env`, then:

```bash
cd apps/api
uvicorn app.main:app --reload
```

Verify it:

```bash
curl -s http://localhost:8000/health
```

```json
{
  "status": "ok",
  "version": "0.1.0",
  "environment": "local",
  "checks": {
    "database": { "status": "up", "latency_ms": 3.26, "error": null }
  }
}
```

`GET /health` answers `200` when the database responds and `503` with
`"status": "degraded"` when it does not. Interactive docs are at
<http://localhost:8000/docs>.

### 5. Start the web app

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev
```

Open <http://localhost:3000>. The page reports the API and database status.

## Database migrations

Alembic reads its database URL from the application settings, so no credentials
live in `alembic.ini`. Run from `apps/api`:

```bash
alembic current                                  # show applied revision
alembic revision --autogenerate -m "add traces"  # create a revision
alembic upgrade head                             # apply revisions
```

No revisions exist yet — no models have been defined in this milestone.

## Tests

```bash
# API (unit tests; database-backed tests are skipped)
cd apps/api && pytest

# API including the live-database test (PostgreSQL must be running)
cd apps/api && RUN_INTEGRATION_TESTS=1 pytest

# SDK
cd packages/python-sdk && pytest

# Web
cd apps/web && npm run lint && npx tsc --noEmit && npm run build
```

## SDK usage

```python
from agenttrace import AgentTracer

tracer = AgentTracer()  # reads AGENTTRACE_API_URL / AGENTTRACE_API_KEY

with tracer.trace("checkout-agent", user="u-1") as trace:
    tracer.record_tool_call("search", {"q": "shoes"}, response=["a", "b"])

print(len(trace.tool_calls))  # 1
```

A runnable version is in [`examples/record_tool_calls.py`](examples/record_tool_calls.py):

```bash
.venv/bin/python examples/record_tool_calls.py
```

## Shutting down

```bash
docker compose down          # stop PostgreSQL, keep data
docker compose down -v       # stop and delete the data volume
```

## Configuration reference

| File | Consumed by | Notes |
| --- | --- | --- |
| `.env` | `docker-compose.yml` | Postgres database, user, password, host port |
| `apps/api/.env` | FastAPI, Alembic | Connection settings and CORS allowlist |
| `apps/web/.env.local` | Next.js | `NEXT_PUBLIC_API_URL` (public, never secret) |
| `packages/python-sdk/.env` | SDK consumers | `AGENTTRACE_API_URL`, `AGENTTRACE_API_KEY` |

Every file has a committed `.env.example`; real `.env` files are gitignored.
