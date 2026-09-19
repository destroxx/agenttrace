# Architecture

## Scope

Built so far: the monorepo, a FastAPI service, PostgreSQL via Docker Compose,
the SQLAlchemy data model and its Alembic migration, the `/api/v1` REST
surface for projects, runs and events, a Python SDK that records a run and
uploads it, and a minimal Next.js app.

Explicitly **not** built: replay, tool mocking, matching, semantic comparison,
evaluation, regression suites, CI integration, authentication, billing,
queues, AWS and Kubernetes.

## Repository layout

```
agenttrace/
├── apps/
│   ├── api/              FastAPI service
│   └── web/              Next.js app
├── packages/
│   └── python-sdk/       `agenttrace` SDK, installed into agent processes
├── examples/             Runnable SDK examples
├── docs/                 This documentation
└── docker-compose.yml    Local PostgreSQL
```

## API module boundaries

Dependencies point inward. Nothing depends on the transport layer, and the
service layer never imports FastAPI.

| Layer | Module | Rule |
| --- | --- | --- |
| Transport | `app/api/` | Routers and dependency wiring. No business logic. |
| Contracts | `app/schemas/` | Pydantic models forming the public API shape. |
| Services | `app/services/` | Business logic. Raises domain errors. |
| Data | `app/models/`, `app/db/` | ORM models, engine, session lifecycle. |
| Config | `app/config.py` | The only module that reads the environment. |

A route resolves a service, calls one method, and converts the result into a
response schema. Services raise `NotFoundError` or `ConflictError`; the two
handlers registered in `app/main.py` turn those into `404` and `409`. No
handler translates errors itself, and no service knows what an HTTP status
code is.

## Data model

```
Project ──< Run ──< Event
```

| Table | Key columns | Notes |
| --- | --- | --- |
| `projects` | `id`, `name`, `description` | Owns runs |
| `runs` | `id`, `project_id`, `agent_name`, `agent_version`, `input`, `output`, `status`, `started_at`, `completed_at` | Owns events |
| `events` | `id`, `run_id`, `sequence`, `event_type`, `tool_name`, `arguments`, `response`, `duration_ms` | One step of a run |

Relationships navigate both ways: `project.runs`, `run.project`, `run.events`,
`event.run`. `Run.events` carries `order_by="Event.sequence"`, so an eagerly
loaded collection is already in replay order. Async code must eager-load
(`selectinload`) — a lazy load in an async context raises rather than
silently blocking.

### Indexes and constraints

| Object | Purpose |
| --- | --- |
| `ix_runs_project_id` | Fetch a project's runs |
| `ix_runs_created_at` | Order runs globally by recency |
| `ix_runs_project_id_created_at` | The list endpoint's actual access path: filter by project, order by recency |
| `ix_events_run_id` | Fetch a run's events |
| `uq_events_run_id_sequence` | **Unique.** Two events cannot claim the same position in a run; the index also serves ordered reads |
| `ck_runs_status_valid` | `status` must be `running`, `completed` or `failed` |

There is deliberately no standalone index on `events.sequence`. A sequence
number is meaningless outside its run, so every real query filters on `run_id`
first; the composite unique index covers that access pattern, and a lone index
on `sequence` would only add write cost.

### Cascades

`runs.project_id` and `events.run_id` are both `ON DELETE CASCADE`, and the
ORM relationships use `cascade="all, delete-orphan"` with
`passive_deletes=True` — the database performs the cascade, and SQLAlchemy
does not load every child row in order to delete it. Deleting a project
removes its runs and their events; deleting a run removes its events and
leaves the project.

## Design decisions

**UUID primary keys.** Traces are produced by SDKs running in other people's
processes, and will eventually be uploaded in batches. A client must be able
to name an entity before the server has seen it, which a sequential integer
cannot do. UUIDs also keep ids non-enumerable, so one customer cannot probe
another's run count. They are generated in Python, not by a server default,
so the id is known the moment the object exists.

**JSONB for payloads.** `runs.input`, `runs.output`, `events.arguments` and
`events.response` are JSONB. Agent and tool payloads have no common shape, and
a column per possible tool argument would mean a migration per new tool.
JSONB keeps them queryable — Postgres can index into them later, which a
`TEXT` blob could not.

**Explicit `sequence`.** Ordering by `created_at` would be wrong: events are
uploaded in batches, timestamps collide at the resolution the database stores,
and a recorder may buffer out of order. Replay needs a total order the client
controls, so the client supplies it, and the unique constraint enforces it.

**Terminal runs are frozen.** A run in `completed` or `failed` state rejects
new events with a conflict, and both closing a run and appending to it take a
row lock on the run, so the two cannot interleave and leave an event stamped
after the run was closed.

**Ingest is one transaction, keyed by the client.** An SDK buffers a whole
execution and uploads it once, so `POST /projects/{id}/runs/ingest` writes the
run and every event together or not at all — a half-stored trace would look to
replay like a complete recording of an agent that stopped early. The run id
comes from the client rather than the database, which is what makes a retried
upload safe: the primary key turns the second attempt into a conflict instead
of a duplicate run. Because the run is new, no row lock is needed.

**`call_id` pairs a call with its answer.** A `tool_call` and the
`tool_response` or `error` that answered it carry the same `call_id`, so an
agent that calls several tools at once can still be reassembled — `sequence`
alone only gives the order, not which response belongs to which call. It is a
string, not a UUID, because the id is minted by whatever made the call and
other SDKs and providers use their own formats.

**Separate Pydantic schemas and ORM models.** The models describe how rows are
stored; the schemas describe what the API accepts and returns. Serialising ORM
objects directly would make every column rename a breaking API change, would
leak fields as soon as one is added, and would trigger lazy loads during
response rendering. `RunCreate` also demonstrates the value of the split: it
has no `status` field at all, because a run may only ever be created as
`running`.

**PostgreSQL.** JSONB, real constraints and transactional DDL in one engine.
The trace data is relational — projects own runs own events — and replay will
depend on that integrity, so a document store would push the ordering and
cascade guarantees into application code.

**Async end to end.** SQLAlchemy 2.x with `asyncpg`, including Alembic's
migration environment. A `DATABASE_URL` naming a sync driver is rewritten onto
`asyncpg` so a provider-issued DSN still works.

## Configuration

Every setting comes from the environment via `pydantic-settings`. Either
`DATABASE_URL` or `POSTGRES_PASSWORD` must be present; a model validator fails
startup with an actionable message if neither is. Both are `SecretStr`, and
`sqlalchemy_url` is a plain property rather than a `computed_field`, so no
credential reaches `repr()` or `model_dump()`. The password is URL-encoded
when the DSN is assembled, so punctuation in it cannot corrupt the URL.

## Migrations

Alembic reads its URL from the same settings object as the application, so
`alembic.ini` holds no credentials, and `app/migrations/env.py` imports
`app.models` so autogenerate sees the metadata. `Base` carries an explicit
constraint naming convention, so every index and constraint has a
deterministic, reversible name.

The test suite runs `alembic upgrade head` against a freshly created
`agenttrace_test` database on every session, so the migration is proven to
build a working schema from empty on each run.

## Testing

Two tiers. Unit tests stub the database session and need no infrastructure.
API tests run against real PostgreSQL: the suite creates and migrates its own
database, then wraps each test in a transaction that is rolled back, so tests
never see each other's rows and development data is never touched. When
PostgreSQL is unreachable those tests skip with a reason; `RUN_INTEGRATION_TESTS=1`
turns the skip into a failure, which is what CI should set.

## SDK

`packages/python-sdk` has **no runtime dependencies**. It is imported into the
user's agent process, so it must not constrain their dependency tree. That
rules out an HTTP client: the transport is `urllib.request`, and an async run
sends from `asyncio.to_thread` so a blocking call never stalls the caller's
event loop.

**Upload happens once, when the run ends.** The SDK buffers the whole
execution and posts it to `/projects/{id}/runs/ingest`, which is what lets the
API write the run and its events in one transaction. The alternative —
streaming each event as it happens — would cost a request per tool call and
would leave partially recorded runs behind whenever an agent died mid-run,
and replay cannot tell such a run from an agent that legitimately stopped
early. The trade-off is explicit and documented for users: a hard process kill
loses the run in flight. Recording is cheap, so the memory cost of holding a
run is not the binding constraint; `completed_traces` is capped at 100 because
a long-running server would otherwise accumulate every run it ever recorded.

**Events are snapshotted at record time, not at upload time.** Upload happens
when the run ends, so an event that merely held a reference to a tool's return
value would record whatever the agent did to that value afterwards -- an agent
that reads a dict and edits it in place would silently rewrite history. A
recording is the fixture every future replay is compared against, so it has to
be immutable the moment it is taken. Each event's `arguments` and `response`,
and the run's `input`, `output` and `metadata`, therefore go through a JSON
round trip (`json.dumps(..., default=str, allow_nan=False)` then `json.loads`)
as they are recorded. The cost is one round trip per event, paid in the agent's
own process; the same pass also settles up front whether a value can be
serialised at all, and rejects `NaN`/`Infinity` here -- where the value can
still degrade to its `repr` -- rather than at the API, which would refuse the
whole upload. `ToolCall.response` deliberately keeps the live object, because
that type predates the transport and callers already reach into it.

**The active trace lives in a `ContextVar`, not on the tracer.** An instance
attribute is shared by every coroutine on the event loop, so two agent runs
started with `asyncio.gather` would record into whichever trace was assigned
last, silently interleaving two executions into one recording. A context
variable gives each task its own view, because a task inherits a copy of the
context at creation. Sequence numbers are still assigned under a
`threading.Lock`, since a synchronous tool may be recorded from a worker
thread, and the number and the append have to happen together or the total
order replay depends on would not hold.

**Recording must never break the host application.** This is the constraint
that shapes the rest: AgentTrace is observability, and observability that
takes down the thing it observes is worse than none. Tool results and
exceptions pass through unchanged — a decorated tool re-raises the original
exception object after recording it — and every failure to record or upload is
logged to the `agenttrace` logger and swallowed. Only `Exception` is caught,
never `BaseException`, so `KeyboardInterrupt` and `asyncio.CancelledError`
still propagate. Uploads are bounded by a configurable timeout, a 409 counts
as success because the client-generated run id makes a retry idempotent, and
payloads are serialised with `json.dumps(default=str)` so an unserialisable
tool argument costs a readable repr rather than the whole trace.
