# Architecture

## Scope

Built so far: the monorepo, a FastAPI service, PostgreSQL via Docker Compose,
the SQLAlchemy data model and its Alembic migration, the `/api/v1` REST
surface for projects, runs and events, a minimal SDK, and a minimal Next.js
app.

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
user's agent process, so it must not constrain their dependency tree. Traces
are held in memory; uploading them to the API above is a later milestone.
