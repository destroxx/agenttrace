# Architecture

## Scope

Built so far: the monorepo, a FastAPI service, PostgreSQL via Docker Compose,
the SQLAlchemy data model and its Alembic migration, the `/api/v1` REST
surface for projects, runs and events, a Python SDK that records a run and
uploads it, replay of a recorded run against a new version of the agent with
deterministic tool-call matching, and a minimal Next.js app.

Explicitly **not** built: comparison of a replay against its recording
(pass/fail), the LLM matching fallback, evaluation, regression suites, CI
integration, a dashboard, authentication, billing, queues, AWS and Kubernetes.

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
response schema. Services raise `NotFoundError`, `ConflictError` or
`UnprocessableError`; the handlers registered in `app/main.py` turn those into
`404`, `409` and `422`. No handler translates errors itself, and no service
knows what an HTTP status code is.

`UnprocessableError` exists for body rules that need the database — today,
that `replay_of_run_id` names a run in the same project. Pydantic cannot check
that, but to the caller it is the same kind of mistake as any other invalid
field, so it answers `422` in FastAPI's own validation-error shape
(`{"detail": [{"loc": ["body", field], "msg": ..., "type": "value_error"}]}`)
rather than a `404` that would read as "your URL is wrong".

## Data model

```
Project ──< Run ──< Event
```

| Table | Key columns | Notes |
| --- | --- | --- |
| `projects` | `id`, `name`, `description` | Owns runs |
| `runs` | `id`, `project_id`, `agent_name`, `agent_version`, `input`, `output`, `metadata`, `status`, `started_at`, `completed_at`, `replay_of_run_id` | Owns events; a replay points at its recording |
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
| `ix_runs_replay_of_run_id` | Find every replay of a recording |
| `fk_runs_replay_of_run_id_runs` | A replay's recording must exist; `ON DELETE SET NULL` |
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

`runs.replay_of_run_id` is the exception: `ON DELETE SET NULL`. A replay is a
run in its own right, so deleting the recording it was replayed against should
not silently delete it, and should not be blocked by it either. The replay
keeps its trace and loses only the link. Same-project is enforced in
`RunService.ingest`, not by the schema — a composite foreign key would need a
redundant unique `(id, project_id)` on `runs` for one check.

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
whole upload. `ToolCall` carries the same snapshots the events do, so there is
one recording and two views onto it, never two versions of the truth.

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

## Replay and tool-call matching

Replay runs the customer's own agent entry point a second time — the same
function that records in production — with every `@tracer.tool` call answered
from a recording instead of executing. `tracer.replay(recording, agent_fn)`
calls `agent_fn(recording.input)`; the agent opens its own `tracer.trace(...)`
as it always does, and that trace is marked `replay_of_run_id = recording` and
uploaded like any other run.

**Why replay runs in the SDK, not the API.** The thing being tested is the
agent's code, and that code only runs in the customer's process. The API could
serve recorded answers over HTTP, but the tools are Python functions the agent
calls directly; intercepting them where they are called is the only place that
needs no change to the agent. It also keeps a replay usable offline:
`Recording.from_trace` replays a run recorded moments earlier in the same
process, with no API at all.

**Real tools never run.** Inside a replay the decorator answers from the
recording whether or not a trace is open, and never falls through to the real
function — not even for a call it cannot match. The session lives in a
module-level `ContextVar`, not one per tracer: an agent's tools are often
decorated by a different `AgentTracer` instance than the one `replay` was
called on, and a per-tracer session would leave those tools live.

**The matching ladder.** Implemented as pure functions in
`agenttrace/matching.py`, so comparison (Phase 6) will use exactly the same
definition of "the same call".

1. *Exact* — same tool name, and the arguments serialise to identical
   canonical JSON (`sort_keys=True`, no whitespace). Both sides go through the
   same `snapshot` recording uses, so a tuple and a list, or a datetime and its
   string, compare as they were recorded.
2. *Normalized* — same tool name, and the arguments are equal after a
   conservative recursive normalisation: strings stripped of surrounding
   whitespace, integer-valued floats turned into ints, and dict keys whose
   value is `None` dropped. List order is kept, and case is **not** folded —
   `"A-1"` and `"a-1"` may be different orders, and merging them would hand one
   customer's data to another's lookup.
3. *LLM-judged* — planned, not built. It would be slow and non-deterministic,
   and a matcher that guesses would let a real regression pass as a match; it
   belongs behind the deterministic tiers, never in front of them.

Tier 1 is tried across every unconsumed candidate before tier 2 is tried at
all, so a loose match never takes the recorded call an exact one was waiting
for.

**Consume-once, lowest sequence first.** Each recorded call answers at most
one live call, and among equal candidates the earliest recorded one wins. That
is what makes repeated identical calls work — an agent polling a job three
times gets the three recorded answers in order, not the first one three times.
Parallel calls (`asyncio.gather`) are safe for the same reason plus a lock:
matching and consuming happen together under one `threading.Lock`, since sync
tools may run in worker threads. Recorded answers are paired with their calls
by `call_id`, not by position, so answers that arrived out of order in the
recording still go to the right call.

**Mismatches.** A live call no recorded call matches raises `UnmatchedToolCall`
inside the agent: there is no recorded answer to give, and calling production
is exactly what replay exists to avoid. The agent may catch it; either way it
is reported as `unmatched`. A recorded call nothing claimed is reported as
`unused` — the new agent skipped a step. A recorded error is re-raised: as
itself when its type is a builtin `Exception` subclass (`TimeoutError`,
`KeyError`), otherwise as `ReplayedToolError` carrying the recorded type name.
Arbitrary names are never imported from a recording. The replay trace records
every call exactly as a live run would, so it is itself a normal, comparable
trace. `ReplayResult` reports facts — matches, unused calls, counts, the
agent's error — and no verdict; deciding pass or fail is comparison's job.

**Recording never raises; replay does.** Recording runs in production inside
someone else's process, where a failure to record must never become a failure
of the agent. Replay is test tooling a developer invokes on purpose, where a
silent failure is the dangerous outcome: a fixture that failed to load and
replayed as empty would look like a regression, or worse, like a pass. So
`Recording.from_api` raises `RecordingNotFound` / `AgentTraceAPIError`, nested
replays raise `ReplayError`, and unmatched calls raise into the agent. The
agent's own exceptions are captured into the result rather than raised, since
a replay that fails is still a result worth inspecting; `BaseException`
propagates.

## Known limitations and deliberate trade-offs

Every item here is a choice made with its cost understood, not an oversight.

**Two clocks, and neither orders a trace.** `runs.started_at` and
`completed_at` come from the client's clock, because only the SDK knows when
the agent actually started; `created_at` comes from the database. A run whose
upload was delayed therefore has a `created_at` later than its `completed_at`,
and two runs recorded on machines with skewed clocks cannot be ordered against
each other by timestamp at all. This is why ordering within a run is
`sequence`, never time — the timestamps are for humans reading a trace, not for
replay.

**No request-size limit on ingest.** `MAX_INGEST_EVENTS` caps the number of
events at 10,000, but nothing caps the bytes, so a single event with a huge
tool response can still make an arbitrarily large request. The limit belongs at
the proxy rather than in application code, and is planned for Phase 9
(deployment); until then a local deployment is trusting its own callers.

**A hard process kill loses the in-flight run.** Nothing is sent until the run
ends, so `SIGKILL`, a power loss or a crashed interpreter takes the whole trace
with it. The alternative — streaming each event — costs a request per tool call
and leaves partially stored traces behind, which replay cannot distinguish from
an agent that legitimately stopped early. Losing a recording is recoverable;
trusting a truncated one is not.

**No authentication.** The SDK sends `AGENTTRACE_API_KEY` as a bearer token and
the API does not check it. Anyone who can reach the API can read or write any
project. This is fine for a local stack and unacceptable for a shared one.

**The upload timeout is per socket operation.** `AGENTTRACE_TIMEOUT` is handed
to `urllib`, where it bounds each socket read or write rather than the request
as a whole, so a server that keeps trickling bytes can hold an upload open for
longer than the configured value. A true wall-clock deadline would mean
managing the connection by hand.

**Unserialisable values degrade as a whole, not per field.** A value that
cannot be JSON-encoded — `NaN`, `Infinity`, a circular reference — is recorded
as the `repr` of the entire value, so `{"score": NaN, "ok": true}` becomes one
string and `ok` stops being separately queryable. Salvaging field by field
would need a recursive walker; degrading whole values keeps the rule easy to
state and easy to spot when reading a trace.

**Tools called outside the trace's context are not recorded.** The active trace
lives in a `ContextVar`, and only `asyncio.to_thread` copies the current
context into the worker. A tool invoked through `loop.run_in_executor` or a raw
`threading.Thread` sees no active trace: it runs and returns normally, but
nothing about it reaches the recording. Use `asyncio.to_thread` for synchronous
tools.

**Only `@tracer.tool` functions are replayable.** A call recorded with
`tracer.record_tool_call` was made by the agent's own code before the SDK saw
it, so during replay the tool has already run; the call is recorded into the
replay trace as usual but cannot be answered from the recording, and its
recorded counterpart shows up as unused. Likewise the agent's own LLM calls run
live during replay unless they are wrapped as tools — replay controls what the
tools say, not what the model does with it.

**Replay feeds the recorded input, as recorded.** `agent_fn` receives
`recording.input`, which is the snapshot of what was passed to
`tracer.trace(input=...)`. An agent that did not record everything it needed
cannot be replayed faithfully, and a non-dict input arrives wrapped as
`{"value": ...}`, because that is how it was stored.

**Replayed errors are rebuilt from a name and a message.** Only builtin
exception types are rebuilt as themselves; the recording holds no traceback,
no attributes and no exception chain, so an agent that inspects those sees
less during replay than it did live.
