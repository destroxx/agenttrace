# AgentTrace

[![CI](https://github.com/destroxx/agenttrace/actions/workflows/ci.yml/badge.svg)](https://github.com/destroxx/agenttrace/actions/workflows/ci.yml)

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

  ✅ implemented   ✅ implemented  ✅ implemented   ✅ deterministic
                                                   ⬜ semantic
```

All four steps work today. **Compare** is deterministic: it turns a replay into
PASS or FAIL with a finding for each difference (a skipped step, an unexpected
call, a changed output field). Judging whether two differently worded answers
mean the same thing — semantic comparison — is not built yet.

## Status

| | Milestone | What it means |
| --- | --- | --- |
| ✅ | Foundation | Monorepo, FastAPI service, Postgres via Compose, Next.js app |
| ✅ | Data model & REST API | `Project ──< Run ──< Event`, `Comparison`, `ApiKey`, 17 endpoints, Alembic migrations |
| ✅ | Frozen terminal runs | A finished run rejects new events; row lock serialises close vs. append |
| ✅ | One-request ingest | A whole finished run and its trace in a single transaction |
| ✅ | Python SDK recorder | Async/sync tracing, `@tracer.tool`, end-of-run upload, record-time snapshots |
| ✅ | Replay | Re-run an agent's own entry point with recorded tool results served back; exact → normalized matching |
| ✅ | Compare (deterministic) | Replay → PASS/FAIL with findings; configurable severities and ignored output paths |
| ⬜ | Semantic comparison | Judge whether a reworded answer means the same thing; reworded text is a warning until then |
| ✅ | Regression suites | Recordings committed in your repo, a `suite.toml`, and `agenttrace run-suite` — offline, exit 1 on any FAIL |
| ✅ | CI integration | GitHub Actions runs every check and the regression suite on each push and pull request |
| ✅ | Dashboard | Read-only: projects, runs with verdicts, a run's timeline and its comparison report |
| ✅ | API keys | Every write needs a key; a project key writes to its own project only; keys stored as hashes; reads stay public |
| ⬜ | Billing, queues, deployment | Not started |

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
- **Replay runs the unchanged agent, in the SDK.** Decorated tools answer from
  the recording and never execute; calls are matched exactly, then after a
  conservative normalisation, each recorded answer used once.
  [Details](docs/architecture.md#replay-and-tool-call-matching)
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

### 4. Make an admin key and start the API

Writes need an API key. The admin key creates projects and issues each project
its own key; the API is configured with its SHA-256, never the key itself:

```bash
cd apps/api
python -m scripts.new_admin_key
```

```
admin key (keep it secret):   at_Xq3…
ADMIN_KEY_SHA256=54457bde…
```

Add the `ADMIN_KEY_SHA256=…` line to `apps/api/.env`, keep the key itself
somewhere safe (a password manager), then start the API:

```bash
uvicorn app.main:app --reload
```

- Health: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>

### 5. Record your first run

With the API running, in a second shell, create a project with the admin key
and issue it a project key — the key the SDK uploads with:

```bash
source .venv/bin/activate
ADMIN_KEY=at_Xq3…                      # the admin key from step 4

export AGENTTRACE_PROJECT_ID=$(curl -s -X POST localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'content-type: application/json' \
  -d '{"name":"Demo"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
export AGENTTRACE_API_KEY=$(curl -s -X POST localhost:8000/api/v1/projects/$AGENTTRACE_PROJECT_ID/keys \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'content-type: application/json' \
  -d '{"name":"laptop"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])')

python examples/async_support_agent.py
```

The project key is shown only in that response; the API keeps its hash. It can
write to this project and nowhere else.

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

<http://localhost:3000> is the product site. The read-only dashboard is at
<http://localhost:3000/projects>: projects, their runs with PASS/FAIL verdicts,
each run's timeline, and its comparison report. It changes nothing.

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

### Replay

Replay runs your agent's normal entry point again, with every `@tracer.tool`
answered from a recording instead of executing. The agent code does not
change:

```python
from agenttrace import Recording

recording = await Recording.from_api(run_id)          # or Recording.from_trace(trace)
result = await tracer.replay(recording, run_agent, agent_version="v2.0.0")

result.status, result.output, result.error            # how the new agent's run went
result.summary                                        # exact / normalized / unmatched / unused
for match in result.matches:                          # one per tool call the new agent made
    print(match.tool_name, match.tier, match.recorded_arguments, match.new_arguments)
for skipped in result.unused:                         # recorded calls it never made
    print(skipped.tool_name, skipped.arguments)
```

`run_agent(input)` is called with the recorded input and must open its own
`tracer.trace(...)`. That trace uploads like any run, with `replay_of_run_id`
pointing at the recording. A call no recording matches raises
`UnmatchedToolCall` inside the agent rather than reaching the real tool.

```bash
.venv/bin/python examples/replay_demo.py
```

records the example agent once and replays four versions of it — unchanged, one
that skips a step, one that looks orders up with the wrong id, and one that only
rewords its reply — printing a side-by-side table and a comparison report for
each, and proving no real tool ran.

### Compare

`replay_and_compare` replays and then judges the replay against its recording:

```python
from agenttrace import ComparisonPolicy

result, report = await tracer.replay_and_compare(
    recording,
    run_agent,
    agent_version="v2.0.0",
    policy=ComparisonPolicy(ignore_paths=["generated_at"]),   # optional
)
print(report.format())
assert report.passed
```

```
FAIL  1 error, 0 warnings, 0 info  (recording a1b2… -> replay 06ac…)
  error    MISSING_TOOL_CALL  get_delivery_status(order_id="B-2") was recorded (seq 9) but never called
```

The verdict is FAIL if any finding is an error. By default a skipped or
unexpected tool call, a changed status, an agent error and a structural output
change (a key added or removed, a number changed) are errors; arguments that
matched only after normalization, a changed call order and **reworded output
text** are warnings. Rewording is a warning because exact text equality is
brittle for natural-language agents; judging meaning is the planned semantic
layer's job. `ComparisonPolicy(severity_overrides={"OUTPUT_TEXT_CHANGED":
"error"})` makes it strict. `compare(recording, result, policy)` works on any
replay result, and `report.to_dict()` is a stable, JSON-serialisable form.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTTRACE_API_URL` | `http://localhost:8000` | Where the API lives |
| `AGENTTRACE_API_KEY` | _unset_ | A project key for `AGENTTRACE_PROJECT_ID`, sent as a bearer token; uploads without one get `401` |
| `AGENTTRACE_PROJECT_ID` | _unset_ | The project runs are uploaded to |
| `AGENTTRACE_TIMEOUT` | `5` | Seconds to wait for one upload |

**Uploading is opt-in**: without `AGENTTRACE_PROJECT_ID` the SDK keeps traces in
memory and never opens a socket, so it is safe to import in tests and offline.

### Run a regression suite

A suite lives in your repo: a `suite.toml` naming the agent's entry point and
a list of cases, each a recording saved as JSON. It runs fully offline.

```bash
agenttrace run-suite examples/suites/support/suite.toml; echo "exit=$?"
```

```
PASS  two-orders
suite support: 1 passed, 0 failed
exit=0
```

Exit `0` means every case passed, `1` that at least one FAILed (each failure's
errors are listed under it), and `2` that the suite itself could not run. A case
the tool could not replay prints `ERROR` and also makes the exit code `2`.
Add a case by exporting a stored run — review it for secrets and personal data
before committing it:

```bash
agenttrace export $RUN_ID -o examples/suites/support/recordings/refund.json
```

It prints the `[[cases]]` entry to paste into `suite.toml`, and refuses to
overwrite an existing recording without `--force`. `python -m agenttrace` works
too. See [`docs/architecture.md`](docs/architecture.md#regression-suites) for why
suites live in the repo rather than on the server.

### Run your suite in CI

A suite needs no API, no database and no secrets, so running it in CI is a
checkout, an install and one command. The SDK is **not on PyPI yet**; install
it from this repository. Copy this into your repo as
`.github/workflows/regression-suite.yml`:

```yaml
name: Regression suite
on: [push, pull_request]
permissions:
  contents: read
jobs:
  suite:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt   # your agent's own dependencies
      - run: pip install "agenttrace @ git+https://github.com/destroxx/agenttrace@main#subdirectory=packages/python-sdk"
      - run: agenttrace run-suite path/to/suite.toml --agent-version "${{ github.sha }}"
```

The job fails on exit `1` (a case regressed) and on exit `2` (the suite could
not run); the log says which. `@main` follows this repo's latest commit — pin
a commit SHA instead if you want the SDK to change only when you change it.
Leave `AGENTTRACE_PROJECT_ID` unset: nothing needs uploading for a verdict.

This repository runs the same way on itself — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) and
[`docs/architecture.md`](docs/architecture.md#continuous-integration).

Full SDK documentation, including known limitations, is in
[`packages/python-sdk/README.md`](packages/python-sdk/README.md).

## API

All endpoints are under `/api/v1`, except `/health`, which is unversioned
because it describes the process rather than the API contract.

**Authentication.** Reads are public. Every write needs an API key, sent as
`Authorization: Bearer <key>`. The **Key** column says which: *project* means a
key issued for that project (the admin key works too); *admin* means the admin
key only. A project key is stored as a SHA-256 hash and shown once, when it is
issued; the admin key is configured as `ADMIN_KEY_SHA256` and is never stored
at all.

| Method | Path | Key | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | — | API and database health; `503` when degraded |
| POST | `/api/v1/projects` | admin | Create a project |
| GET | `/api/v1/projects` | — | List projects (paginated) |
| GET | `/api/v1/projects/{project_id}` | — | Get a project |
| POST | `/api/v1/projects/{project_id}/keys` | admin | Issue a project key; the response is the only place it appears |
| GET | `/api/v1/projects/{project_id}/keys` | admin | List a project's keys by prefix, revoked ones included |
| DELETE | `/api/v1/keys/{key_id}` | admin | Revoke a key; it gets `401` from the next request on |
| POST | `/api/v1/projects/{project_id}/runs` | project | Start a run (status `running`) |
| POST | `/api/v1/projects/{project_id}/runs/ingest` | project | Upload one finished run and its whole trace |
| GET | `/api/v1/projects/{project_id}/runs` | — | List a project's runs with event count, duration and verdict (paginated, `?status=`) |
| GET | `/api/v1/runs/{run_id}` | — | Get a run |
| POST | `/api/v1/runs/{run_id}/complete` | project | Record output and final status |
| POST | `/api/v1/runs/{run_id}/events` | project | Append an event |
| GET | `/api/v1/runs/{run_id}/events` | — | List events ordered by `sequence` |
| POST | `/api/v1/runs/{run_id}/comparison` | project | Store the comparison report for a replay run |
| GET | `/api/v1/runs/{run_id}/comparison` | — | Get a replay run's comparison report |
| GET | `/api/v1/projects/{project_id}/comparisons` | — | List a project's reports, counts only (paginated) |

Errors: `401` for a missing, unknown or revoked key; `403` for a project key
used on another project's data, or on an admin route; `404` for a missing
project or run; `409` for a duplicate event
sequence, a run that has already finished, an event posted to a finished run, or
re-uploading a run id that is already stored, or a second report for the same
run; `422` for a malformed body, a path id that is not a UUID, an ingest
`replay_of_run_id` that is not a run in the same project, or a report on a run
that is not a replay of the report's recording.

Paginated endpoints take `?page=1&page_size=20` (`page_size` caps at 100) and
return `{"items": [...], "total": n, "page": n, "page_size": n}`.

The SDK uses `ingest`. The step-by-step path exists for recorders that cannot
buffer a whole run:

```bash
API=http://localhost:8000/api/v1
RUN=d8686012-6e56-483f-bbfc-c69c22d91f52   # from POST /projects/$PROJECT/runs
AUTH="Authorization: Bearer $AGENTTRACE_API_KEY"

curl -s -X POST $API/runs/$RUN/events -H "$AUTH" -H 'content-type: application/json' \
  -d '{"sequence":1,"event_type":"agent_start"}'
curl -s -X POST $API/runs/$RUN/events -H "$AUTH" -H 'content-type: application/json' \
  -d '{"sequence":2,"event_type":"tool_call","call_id":"call_abc123",
       "tool_name":"get_order","arguments":{"order_id":"12345"}}'
curl -s -X POST $API/runs/$RUN/events -H "$AUTH" -H 'content-type: application/json' \
  -d '{"sequence":3,"event_type":"tool_response","call_id":"call_abc123",
       "tool_name":"get_order","response":{"status":"in_transit"},"duration_ms":42}'
curl -s -X POST $API/runs/$RUN/complete -H "$AUTH" -H 'content-type: application/json' \
  -d '{"output":{"message":"Arriving tomorrow."},"status":"completed"}'
```

Order of insertion does not matter — reads are always ordered by `sequence`. A
finished run answers `409` rather than overwriting its recorded output, and two
events cannot claim the same `sequence` within a run.

Optionally load one realistic trace to poke at:

```bash
cd apps/api && python -m scripts.seed_dev_data
```

It is not idempotent — each run creates a new project. It writes through the
services directly, as the admin, so it needs no key: whoever can run it already
holds the database password.

## Deploy to Vercel

The whole stack deploys as **one Vercel project** using
[Services](https://vercel.com/docs/services) (`vercel.json` at the repo root):
the Next.js site and dashboard, and the FastAPI service as a Python function,
on one domain. Postgres comes from [Neon](https://vercel.com/marketplace/neon)
through the Vercel Marketplace. Both have free tiers.

```
              <project>.vercel.app
                       │
     ┌─────────────────┴──────────────────┐
     │ /api/v1/*, /health, /docs          │ everything else
     ▼                                    ▼
  api  (apps/api, FastAPI)            web  (apps/web, Next.js)
     │                ▲                   │
     ▼                └── private binding ┘  (server-side dashboard reads)
  Neon Postgres
```

One origin means no CORS, and the browser's requests are relative, so every
preview deployment talks to its own API. The dashboard's server-side reads use
a private [binding](https://vercel.com/docs/services/bindings)
(`AGENTTRACE_API_INTERNAL_URL`) to the same deployment's API.

**1. Import the repository** at <https://vercel.com/new> (or `vercel link` from
the repo root). Keep the root directory as the repository root; `vercel.json`
names both services.

**2. Add Neon** from the project's **Storage** tab (or
`vercel integration add neon`). It injects `DATABASE_URL` (pooled, used by the
app) and `DATABASE_URL_UNPOOLED` (direct, used by migrations) into the project.

**3. Set the API's settings** for the Production environment:

| Variable | Value |
| --- | --- |
| `ADMIN_KEY_SHA256` | From `python -m scripts.new_admin_key` — make a new key for production, never reuse a local one |
| `ENVIRONMENT` | `production` |

**4. Deploy** — push to `main`, or `vercel --prod`. The API's build step
(`scripts/vercel_build.py`) runs `alembic upgrade head` against the production
database before the deployment goes live; a failing migration fails the
deployment and leaves the previous one serving. Preview deployments skip
migrations, because their code is unmerged and the database is production's.
If each preview gets its own Neon branch, set `AGENTTRACE_MIGRATE_PREVIEWS=1`
for the Preview environment and previews migrate their branch instead.

**5. Fill it with demo data** from your machine, with the production admin key:

```bash
export AGENTTRACE_API_URL=https://<project>.vercel.app
ADMIN="Authorization: Bearer <production admin key>"
export AGENTTRACE_PROJECT_ID=$(curl -s -X POST $AGENTTRACE_API_URL/api/v1/projects \
  -H "$ADMIN" -H 'content-type: application/json' -d '{"name":"Support agent demo"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')
export AGENTTRACE_API_KEY=$(curl -s -X POST $AGENTTRACE_API_URL/api/v1/projects/$AGENTTRACE_PROJECT_ID/keys \
  -H "$ADMIN" -H 'content-type: application/json' -d '{"name":"demo seeding"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])')
python examples/async_support_agent.py && python examples/replay_demo.py
```

Agents anywhere then record to the deployment with `AGENTTRACE_API_URL` set to
it and a project key in `AGENTTRACE_API_KEY`.

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
├── docker-compose.yml    Local PostgreSQL
└── vercel.json           Deployment: the web and api services and their routes
```

Inside `apps/api`, dependencies point inward and nothing depends on transport:
routes (`app/api/`) carry no business logic, services (`app/services/`) never
import FastAPI and raise only the five domain errors in `app/services/exceptions.py`, and
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

Currently 137 API tests and 188 SDK tests. The API suite owns a separate database
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

**Uploads log `failed with status 401` or `403`.** The run was recorded but
not stored. `401`: `AGENTTRACE_API_KEY` is unset, mistyped or revoked — issue a
new key with `POST /api/v1/projects/{project_id}/keys`. `403`: the key belongs
to a different project than `AGENTTRACE_PROJECT_ID`. The agent itself is never
affected; the log line says which of the two it was.

**`pytest -v` prints no per-test list.** `pyproject.toml` sets `addopts = "-q"`,
which cancels it. Use `pytest -o addopts="" -v`.

## Known limitations

The deliberate trade-offs — end-of-run upload losing a run to a hard kill, the
per-socket upload timeout, unrecorded tools in raw threads, only `@tracer.tool`
being replayable, and more — are listed in
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
| `apps/api/.env` | FastAPI, Alembic, tests | `DATABASE_URL` or `POSTGRES_*` (and optionally `DATABASE_URL_UNPOOLED` for migrations), CORS allowlist, `ADMIN_KEY_SHA256` |
| `apps/web/.env.local` | Next.js | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL` (public, never secret); on Vercel both default from the deployment (`next.config.ts`) |
| `packages/python-sdk/.env` | SDK consumers | `AGENTTRACE_API_URL`, `AGENTTRACE_API_KEY`, `AGENTTRACE_PROJECT_ID`, `AGENTTRACE_TIMEOUT` |

Every file has a committed `.env.example`; real `.env` files are gitignored.
