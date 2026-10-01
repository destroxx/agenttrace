# Architecture

## Scope

Built so far: the monorepo, a FastAPI service, PostgreSQL via Docker Compose,
the SQLAlchemy data model and its Alembic migration, the `/api/v1` REST
surface for projects, runs and events, a Python SDK that records a run and
uploads it, replay of a recorded run against a new version of the agent with
deterministic tool-call matching, a deterministic comparison of a replay
against its recording (pass/fail with findings), storage of those reports, a
read-only Next.js dashboard over projects, runs, traces and reports, and
regression suites kept in the developer's repo, run by the `agenttrace` CLI,
a GitHub Actions workflow that runs every check and the suite, and API keys
that guard every write.

Explicitly **not** built: semantic (LLM-judged) comparison, the LLM matching
fallback, evaluation, user accounts, billing, queues, AWS and Kubernetes.

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
response schema. Services raise `NotFoundError`, `ConflictError`,
`UnprocessableError`, `AuthenticationError` or `PermissionDeniedError`; the
handlers registered in `app/main.py` turn those into `404`, `409`, `422`, `401`
and `403`. No handler translates errors itself, and no service
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
   │         │
   │         └──? Comparison      (a replay run's report; at most one)
   └──< ApiKey                    (stored as a hash; writes to this project only)
```

| Table | Key columns | Notes |
| --- | --- | --- |
| `projects` | `id`, `name`, `description` | Owns runs |
| `runs` | `id`, `project_id`, `agent_name`, `agent_version`, `input`, `output`, `metadata`, `status`, `started_at`, `completed_at`, `replay_of_run_id` | Owns events; a replay points at its recording |
| `events` | `id`, `run_id`, `sequence`, `event_type`, `tool_name`, `arguments`, `response`, `duration_ms` | One step of a run |
| `comparisons` | `id`, `replay_run_id`, `recording_run_id`, `verdict`, `report`, `created_at` | The SDK's report on one replay |
| `api_keys` | `id`, `project_id`, `name`, `prefix`, `key_hash`, `created_at`, `revoked_at` | A project key; the key itself is never stored |

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
| `uq_comparisons_replay_run_id` | **Unique.** One report per replay run; also serves the run list's join |
| `ix_comparisons_recording_run_id` | Find the reports about a recording |
| `fk_comparisons_*_runs` | Both runs must exist; `ON DELETE CASCADE` on each |
| `ck_comparisons_verdict_valid` | `verdict` must be `pass` or `fail` |
| `uq_api_keys_key_hash` | **Unique.** Authentication is one lookup by hash, and this index is it |
| `ix_api_keys_project_id` | List a project's keys |
| `fk_api_keys_project_id_projects` | `ON DELETE CASCADE`: a key for a deleted project can write nowhere |

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

`comparisons` cascades from **both** of its runs. A report without either run
it compares cannot be read meaningfully, and keeping it would leave a verdict
pointing at nothing. The two rules meet when a recording is deleted: its
replays survive (`replay_of_run_id` becomes null) but their reports are
deleted with it, so those replays keep their traces and lose their verdicts.

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

**A provider's DSN is translated for asyncpg.** Managed Postgres hands out
libpq-style URLs — Neon's ends `?sslmode=require&channel_binding=require` —
and SQLAlchemy passes query options to the driver as keywords. asyncpg takes
`ssl`, not `sslmode`, and has no `channel_binding`, so an untranslated DSN
connects nowhere: it fails at the first query, not at startup. `_as_async_dsn`
renames `sslmode` to `ssl`, drops `channel_binding` (asyncpg negotiates SCRAM
itself), and keeps every other option. A test checks the final keywords
against `asyncpg.connect`'s real signature, so a driver upgrade that changes
them fails CI rather than production.

**Migrations can use their own DSN.** `DATABASE_URL_UNPOOLED`, when set, is
what Alembic connects with. A pooler in transaction mode suits short request
queries, but migrations take locks across statements and belong on a direct
connection; Neon's Vercel integration injects both URLs.

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
`agenttrace/matching.py`, so comparison uses exactly the same definition of
"the same call".

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

## Comparison engine

`compare(recording, replay_result, policy=None)` in `agenttrace/comparison.py`
turns a replay into a `ComparisonReport`: a verdict (`pass` / `fail`) and the
findings behind it. `tracer.replay_and_compare(...)` is replay followed by
compare, nothing more. The module is pure — no I/O, no tracer state, no clock,
no randomness — so the same recording and replay always give the same report,
byte for byte from `to_dict()`.

**It reads replay's facts rather than re-deriving them.** Which live call
matched which recorded one, at which tier, and which recorded calls went
unused are all decided once, by `matching.py`, during replay. Comparison reads
`ReplayResult.matches` and `.unused` and never matches anything itself, so
replay and comparison cannot disagree about what "the same call" means. The
output diff reuses `matching.normalize` for the same reason: a difference that
cannot tell two tool calls apart — surrounding whitespace, `2` vs `2.0`, a key
set to `None` vs left out — is not reported for outputs either.

**Three levels, strictest first.**

1. *Exact* — calls and output identical; no findings.
2. *Behavioral* — built. Each difference is a `Finding` with a code:
   `MISSING_TOOL_CALL` (a recorded call never made), `UNEXPECTED_TOOL_CALL`
   (a live call nothing recorded matches), `ARGUMENTS_NORMALIZED`,
   `TOOL_ORDER_CHANGED`, `STATUS_CHANGED`, `AGENT_ERROR`,
   `OUTPUT_STRUCTURE_CHANGED` (a key added or removed, a type, number or
   boolean changed, a list length changed), `OUTPUT_TEXT_CHANGED` (only the
   wording of a string differs) and `OUTPUT_MISSING`.
3. *Semantic* — planned, not built. Whether "arriving tomorrow" and "due
   tomorrow" mean the same thing needs a model, which is neither deterministic
   nor free; it belongs on top of the deterministic levels, judging only what
   they flag as a wording change.

**The verdict is severity-driven and configurable.** Every finding is
`error`, `warning` or `info`; the verdict is `fail` if any is an error. What
counts as an error is policy, not mechanism — an agent whose tool order is
irrelevant and one where it never is want different rules from the same
facts — so `ComparisonPolicy` can override any code's severity, and mark
output paths expected to vary (`"timestamp"`, `"items.*.id"`). A difference
at an ignored path is still reported, as `info`: it never fails the verdict,
and it is never silently hidden either. A misspelt code or severity in a policy
raises at construction, since an override that silently did nothing would make
a suite stricter or looser than its author believes.

Defaults: errors are the missing and unexpected calls, a status change, an
agent error, a structural output change and a missing output. Warnings are
normalized arguments, a changed order and a text change.

**Why `OUTPUT_TEXT_CHANGED` defaults to a warning.** Exact text equality is
brittle for agents that answer in natural language: a model rephrasing its
reply is the normal case, not a regression, and a suite that fails on every
rewording gets ignored. Deciding whether two wordings mean the same thing is
the semantic layer's job; until it exists the change is surfaced, not failed.
Teams that need word-for-word output raise it to `error`.

**Why order is checked, and how.** An agent that confirms a booking *after*
making it, or refunds before checking eligibility, makes exactly the recorded
calls and is still broken. The matched calls are taken in the order the
replay made them, and each adjacent pair whose recorded sequences go
backwards is one `TOOL_ORDER_CHANGED` — so moving one step from first to last
is one finding, not one per step it jumped over. It defaults to a warning
because concurrent tools (`asyncio.gather`, worker threads) can legitimately
start in a different order from run to run.

**Stable order.** Findings sort by severity; within a severity, run-level
findings first, then tool calls by recorded sequence, then output fields by
path. Unexpected calls have no recorded position and sort by tool name and
arguments, so the report does not depend on which of several parallel calls
happened to start first.

**Why comparison lives in the SDK.** A CI job needs a verdict locally, from a
recording it may have fetched moments ago or recorded in the same process,
without a round trip to a service. The API stores reports so they can be looked
at later, but never computes or changes a verdict.

## Stored reports and the dashboard

`tracer.replay_and_compare` uploads the report next to the replay run it
describes, when uploading is configured. Three endpoints serve them:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/runs/{run_id}/comparison` | Store the report for a replay run |
| GET | `/api/v1/runs/{run_id}/comparison` | Get it; `404` for a run with no report |
| GET | `/api/v1/projects/{project_id}/comparisons` | A project's reports, newest first, counts only |

**A report belongs to a replay of exactly that recording.** The run in the URL
must have `replay_of_run_id` set, and it must equal the report's
`recording_run_id`; the recording must also be in the same project. Anything
else is a `422` on `recording_run_id`. Without this, a plain recording could be
given a report — even one "about" itself — and would show a PASS/FAIL badge
for a comparison that never happened. As with ingest, an unknown recording and
another project's get the same answer.

**Reports are immutable.** `replay_run_id` is unique, and a second report for
the same run is a `409` rather than a replacement, so a verdict someone has
already seen cannot quietly change. The SDK counts that `409` as "already
stored", which makes its upload safe to retry. The report is stored verbatim
as JSONB — its shape belongs to the SDK — and the API also checks that the
verdict agrees with the findings it summarises. `verdict` is copied out of the
report into its own column so run lists can show it with a join instead of
reading JSON per row.

**List summaries are computed in SQL.** `GET /projects/{id}/runs` returns each
run with `event_count`, `duration_ms` and `verdict`, and `GET /projects` returns
each project with `run_count` and `last_run_at`. They come from the query that
pages the rows — correlated counts over the existing `run_id` / `project_id`
indexes and an outer join to `comparisons` — so a page costs a fixed number of
queries however many rows it holds. `duration_ms` is `completed_at -
started_at`, from the client's clock, and null while a run is running. The runs
list also takes `?status=`.

**The dashboard is read-only.** It shows projects, runs, a run's timeline and
its report; it creates, edits and deletes nothing. Every write in AgentTrace
comes from the SDK, next to the agent, and the recordings are fixtures whose
value is that nothing changes them after the fact. A dashboard that could edit
a run or a verdict would be a second, unaudited way to rewrite history — and
it would need its own login, where a read-only one needs none.

**The dashboard is always dark**, whatever the OS theme, like the marketing
site: one brand from the site to the app, and one theme instead of two halves
the surface to design and check.

## Authentication

Every write needs an API key, sent as `Authorization: Bearer <key>`; every read
is public. The reads are what a visitor to a demo deployment browses — the
dashboard is read-only and calls only GETs — and the writes are what must not
be forged, because a recording is a test fixture whose value is that nobody
can quietly change it.

**Two kinds of key.** A *project key* is issued for one project and may write
to that project only. The *admin key* creates projects and issues, lists and
revokes project keys; it may also write anywhere. Scoping keys to projects is
the point: a key copied out of one agent's environment or CI log cannot touch
any other project's recordings or verdicts.

**Only hashes are kept.** A project key exists in exactly one place — the
response that issued it — and the database stores its SHA-256 plus an
11-character display prefix (`at_` and eight characters) to tell keys apart.
The admin key is not stored at all: the API is configured with
`ADMIN_KEY_SHA256`, so reading the environment, a database dump or a log yields
nothing that can be sent back. `python -m scripts.new_admin_key` makes a key
and prints its hash. Settings reject anything but a 64-character lowercase hex
digest, so pasting the key itself fails at startup rather than leaving the API
with no admin.

**SHA-256, not bcrypt.** Password hashes are slow on purpose, because passwords
are guessable. These keys are 256 random bits from `secrets.token_urlsafe`;
there is no dictionary to try, so a slow hash would only make every request
slower. A fast hash also makes authentication a single indexed lookup
(`uq_api_keys_key_hash`). The admin hash is compared with
`hmac.compare_digest`; project keys are found by the hash of what was sent, so
the lookup never touches any real key's bytes in a way timing could reveal.

**Where the check happens.** `get_caller` (`app/api/dependencies.py`) turns the
header into a `Caller` — a project id, or none for the admin — and every write
route passes it to its service. The service checks it against the project the
write *really* touches: for `/runs/{run_id}/…` routes that is the run's
project, which only the service, having loaded the run, knows. Reads take no
caller at all, so a new GET is public unless someone deliberately adds one.

**What a caller learns.**
- `401` for no key, an unknown key and a revoked key alike, with one message
  and `WWW-Authenticate: Bearer`, so probing reveals nothing about which keys
  exist or once did.
- `401` comes before body validation: an unauthenticated caller is not told
  what a valid body would look like. (A body that is not JSON at all is
  rejected by FastAPI before any dependency runs; that `422` reveals nothing.)
- `403` for a valid key used on another project, or a project key on an admin
  route. The key's scope is checked before the project's existence, so a
  project key cannot use `404` versus `403` to discover other project ids.

**Revoking keeps the row.** `DELETE /keys/{id}` sets `revoked_at` and the key
gets `401` from the next request on; the list keeps showing it, so which key
was used and when it stopped is still visible. Revoking twice keeps the first
timestamp.

**The SDK needed no change to authenticate** — it already sent
`AGENTTRACE_API_KEY` as a bearer token. It now names the fix when an upload is
refused: a `401` logs "set AGENTTRACE_API_KEY to a valid key for this project",
a `403` that the key belongs to a different project. Recording still never
raises; the agent finishes normally either way.

## Regression suites

A suite is a TOML file in the developer's own repository listing cases, each a
recording saved as a JSON file beside it. `agenttrace run-suite suite.toml`
replays every case against the agent code as it is now, compares, prints one
line per case and a summary, and exits non-zero on any FAIL. It needs no API
and no database.

```
suites/support/
├── suite.toml                 name, agent = "module:function", [policy], [[cases]]
└── recordings/
    └── two-orders.json        one recording: the run plus its events
```

**Suites live in the repo, not on the server.** This was decided up front,
for three reasons. CI must give the same verdict for the same commit, and a
suite fetched from a service could change underneath a commit that did not.
A policy change — a severity raised, an output path ignored — changes what
counts as a regression, so it should go through code review like any other
test change. And a suite that runs offline needs no deployed API and no key —
so no secret in CI.
Server-side datasets would suit a hosted, multi-user product; if they come,
they will sync into the repo rather than replace it.

**The recording file is the export of a stored run.** `agenttrace export
RUN_ID -o PATH` writes `{**run, "events": [...]}` — exactly the API's two
responses, the shape `Recording.from_api_sync` builds — so the file reads back
through `Recording.from_payload` into the same `Recording` a direct fetch
would. There is no second format. The file is written with sorted keys, a
two-space indent, unescaped non-ASCII and a trailing newline, so re-exporting
the same run is a zero-line diff and a real change is a readable one.

**Export refuses to overwrite.** A recording is a frozen fixture: it is what
every future replay is judged against. Silently replacing one would change what
a test asserts without anyone seeing it happen, so an existing file is only
replaced with `--force`, and a run still `running` is refused because it is
not a complete recording.

**Everything is validated before anything runs.** Parse errors, missing or
unknown keys, duplicate case names, a missing or malformed recording and an
invalid policy are all one `SuiteError` naming the file and case, raised while
loading. A suite that ran the cases it could load would report a verdict on
part of itself, and a CI log would read that as the agent's result. An empty
suite is an error too: it would pass without testing anything.

**Policy merging.** A suite-wide `[policy]` applies to every case, and a case's
`[cases.policy]` extends it: `ignore_paths` are the union, and
`severity_overrides` are merged with the case winning per code. A case can be
stricter or looser about a code, but cannot un-ignore a path the suite ignores.

**Exit codes: 0 all passed, 1 any case failed, 2 the suite could not run.**
2 covers a `SuiteError`, an agent that will not import, bad arguments and a
failed export. CI must tell "the agent regressed" apart from "the suite is
broken": the first is for the author of the change, the second for whoever
owns the suite, and conflating them sends the wrong person looking. An agent
that raises during a case is a regression, not a broken suite — its case FAILs
with `AGENT_ERROR` and the remaining cases still run. A case the tool itself
could not replay prints `ERROR` and makes the exit code 2, even beside FAILs,
because a suite with a broken case cannot vouch for its verdict.

**One tracer, any agent.** The CLI builds one `AgentTracer` from the
environment and replays each case through it, while the agent module keeps its
own tracer. This works because the replay session is a module-level
`ContextVar`: every `@tracer.tool`, whichever tracer decorated it, is answered
from the recording. Uploading is unchanged — off unless `AGENTTRACE_PROJECT_ID`
is set. When it is on, the agent's own tracer uploads the replay run and the
CLI's tracer uploads the report; a failed upload is logged and never changes a
verdict. The agent is imported by `module:function` with the working directory
first on `sys.path`, as uvicorn and pytest do, so a suite run from the repo root
can name the agent without it being installed as a package.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main`, every pull request and
on demand. It runs the checks from CLAUDE.md's command list, so CI and a
developer's pre-commit run are the same checks and cannot drift apart
unnoticed. There are four jobs, and each protects something different:

| Job | Runs | Protects |
| --- | --- | --- |
| SDK (Python 3.12, 3.13) | `pytest`, `ruff check packages/python-sdk examples` | The SDK in users' processes, and the examples |
| API | `ruff`, the Alembic round trip to base and back, `alembic check`, `pytest` against a Postgres 16 service | The schema — reversible migrations that match the models — and the API |
| Web | `npm ci`, lint, `next build`, `tsc --noEmit` | The dashboard builds and type-checks |
| Regression suite | `replay_demo.py` with its verdict line pinned, then `agenttrace run-suite` | That the example agent does not regress, and that a suite runs with no API |

**No secrets, and no API.** Suites are offline by design (see Regression
suites), so the regression job installs only the SDK and leaves
`AGENTTRACE_PROJECT_ID` unset: it proves the suite needs nothing but the
repository. The API job's database is a service container that exists for the
length of the job, and its password is a literal in the workflow for that
reason. Workflow permissions are `contents: read` and nothing else: no job
writes to the repository, so no job gets a token that could.

**`RUN_INTEGRATION_TESTS=1`.** Without it, the API tests skip when Postgres is
unreachable — right for a laptop without Docker, wrong for CI, where a
misconfigured service would turn the job green having tested nothing. With it,
an unreachable database fails the job.

**Two Python versions for the SDK.** `requires-python = ">=3.12"` is a claim to
every user on 3.12 and newer, and the SDK runs inside their process, on their
interpreter. The API and the suite run on one version because we choose where
they run.

**Exit codes.** `run-suite` exits `1` when a case regressed and `2` when the
suite could not run. Both fail the job, but the step says which in an error
annotation, and the suite's output is written to the run's summary page either
way — a red run caused by a broken suite file should not send the author of
the change looking for a regression in their agent.

**Every step runs with `shell: bash`, so pipefail is on.** A step without an
explicit shell runs as `bash -e`, without pipefail, and a pipeline then
succeeds or fails with its last command: `agenttrace run-suite … | tee` would
report `tee`'s success and turn a regression green. `shell: bash` runs steps
as `bash -eo pipefail`, so a failure anywhere in a pipe fails the step. It is
set for the whole workflow and again in each job that has its own defaults.

Pull-request runs are cancelled when a newer commit is pushed to the same pull
request; runs on `main` always finish, so every commit on `main` has a result.

## Deployment

The stack deploys as one Vercel project with two
[Services](https://vercel.com/docs/services), defined in `vercel.json`: `web`
(`apps/web`, Next.js) and `api` (`apps/api`, FastAPI as one Python function).
Neon Postgres comes from the Vercel Marketplace. Steps are in the README.

**One project, one origin.** Top-level rewrites send `/api/v1/*`, `/health`,
`/docs` and `/openapi.json` to `api` and everything else to `web`. Vercel
passes the original path through, and the API already serves exactly those
paths, so nothing is stripped or prefixed. Frontend and backend deploy and
roll back together, so the dashboard never runs against an API of a different
version, and every pull request gets a full preview of both. The alternative —
two projects — would mean CORS, two URLs per preview, and a preview dashboard
pointing at production's API.

**Browser requests are relative; server requests use a binding.** On Vercel,
`next.config.ts` sets `NEXT_PUBLIC_API_URL` to empty, so the browser calls
`/health` on whatever deployment served the page. Server-side code cannot use
a relative URL, and a preview's public URL sits behind Vercel's deployment
protection, so the dashboard's server-side reads go through a private service
binding, `AGENTTRACE_API_INTERNAL_URL`, which reaches this deployment's `api`
without the public edge. Locally neither applies and the defaults stay
`http://localhost:8000`. Text the page displays — a `curl` to paste — uses the
site's public URL instead of the empty one.

**Migrations run in the build, in production only.** The API's build step
(the `api` service's `buildCommand` in `vercel.json` → `scripts/vercel_build.py`) runs
`alembic upgrade head` before the deployment goes live, so production never
serves code newer than its schema, and a failing migration fails the deploy
while the previous deployment keeps serving. A preview is unmerged code; given
the production database, its migrations would change production's schema
before review. So previews skip migrations unless
`AGENTTRACE_MIGRATE_PREVIEWS=1` is set for the Preview environment, which is
only right when previews have a database of their own. The deployed project
sets it: Neon's integration gave previews a database separate from
production's — verified, since a project seeded into production is a `404` on
a preview — so a pull request that adds a migration gets a working preview
without touching production. The decision is a pure function with a test per
case; the safe default stays "production only" for anyone deploying a copy
whose previews share one database.

**What the platform changes.** The API runs as a Vercel Function on Fluid
compute: instances are reused across requests, so the engine's connection
pool and `pool_pre_ping` still matter, and instances scale to zero when idle.
Neon's free compute also suspends after a few idle minutes. The first request
after a quiet spell is therefore slower, by up to a few seconds — fine for a
demo. Vercel Functions accept request bodies up to 4.5 MB, which
becomes ingest's practical size limit.

## Packaging and releases

The SDK is published to PyPI as **`agenttrace-replay`**, by
`.github/workflows/release.yml`, when a tag `sdk-v<version>` is pushed.

**Three names, on purpose.** The distribution is `agenttrace-replay`; the
import and the CLI stay `agenttrace`. `agenttrace` on PyPI belongs to an
unrelated project, and a user who typed it would install someone else's code,
so the docs name the distribution everywhere an install command appears. The
version lives once, in `agenttrace.__version__`, and hatchling reads it from
there (`dynamic = ["version"]`).

**The tag must match the code.** PyPI never accepts a version twice, even
after a delete, so a mistake cannot be re-published under the same number. The
release's first step compares the tag with `__version__` and stops before
building if they differ. Then it runs the tests, builds with `uv build`,
checks the metadata with `twine check --strict`, and installs the wheel alone
to run the example suite — the package, not the checkout, has to work.

**No credential exists.** Publishing uses PyPI's trusted publishing: the
publish job holds only GitHub's OIDC token, which PyPI accepts because it was
told in advance to trust this repository, this workflow and the `pypi`
environment. There is no API token to leak or rotate. The upload also attaches
signed provenance attestations (PEP 740), so anyone can check a file on PyPI
was built by this workflow.

**CI builds the package on every change.** The `Package` job runs the same
build, metadata check and wheel smoke test as the release, so a packaging
mistake — a module left out of the wheel, a broken entry point — fails a pull
request instead of a release.

**`run-suite` belongs in the agent's environment.** It imports the agent, so
it must run where the agent's dependencies are installed: the docs recommend
`uv add --dev agenttrace-replay` and `uv run agenttrace run-suite`, not `uvx`,
whose isolated environment only suits commands that import nothing of the
user's, like `export`.

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
the proxy rather than in application code. On Vercel the platform's 4.5 MB
request-body limit is that cap; a self-hosted deployment needs its own proxy
limit. An API key limits who can write, not how much.

**A hard process kill loses the in-flight run.** Nothing is sent until the run
ends, so `SIGKILL`, a power loss or a crashed interpreter takes the whole trace
with it. The alternative — streaming each event — costs a request per tool call
and leaves partially stored traces behind, which replay cannot distinguish from
an agent that legitimately stopped early. Losing a recording is recoverable;
trusting a truncated one is not.

**Reads are public.** Anyone who can reach the API can read every project's
runs, traces and reports. That is the point of a demo deployment and wrong for
private data; per-project read keys would be the next step, and the dashboard
would then need a server-side key of its own.

**Keys are simple.** They do not expire, record when they were last used, or
rotate themselves; there is one admin key, and changing it means redeploying
with a new `ADMIN_KEY_SHA256`. Failed authentication is not rate-limited —
guessing a 256-bit key is hopeless, but a flood of attempts still costs a
query each.

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

**Deleting a recording deletes its replays' verdicts.** A replay's link to its
recording is `SET NULL`, so the replay run and its trace survive, but its
comparison report cascades from the recording and is deleted. There is no
delete endpoint yet, so this only happens through the database directly; when
one exists, a retention policy will have to decide whether a recording that has
been compared against can be deleted at all.

**Recordings are committed verbatim.** A recording holds the run's real input,
output and every tool argument and response — customer names, order details,
anything a tool returned. `export` does not redact, because a fixture that has
been edited no longer records what happened. Review a recording for secrets and
personal data before committing it, and record suites against test accounts
where possible.

**Uploads from a suite fail when the recording is not in the uploading
project.** With `AGENTTRACE_PROJECT_ID` set, a suite's replay runs are uploaded
with `replay_of_run_id` pointing at the recording, and the API accepts that
only for a run stored in the same project. A recording made offline — like the
example suite's — or exported from another project is refused with a `422`, and
its report then fails with a `404`, because the replay run it belongs to was
never stored. Both failures are logged and neither changes the verdict; run
suites without a project id unless the recordings came from that project.
