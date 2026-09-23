# agenttrace (Python SDK)

Records AI-agent executions — tool calls and their responses — so they can be
replayed against a future version of the agent.

## Install (editable, for local development)

```bash
pip install -e "packages/python-sdk[dev]"
```

## Usage

```python
import asyncio
from agenttrace import AgentTracer

tracer = AgentTracer()  # reads the AGENTTRACE_* environment


@tracer.tool
async def get_order(order_id: str) -> dict:
    return {"id": order_id, "status": "shipped"}


@tracer.tool
def format_reply(status: str) -> str:
    return f"Your order is {status}."


async def main() -> None:
    async with tracer.trace(
        "support-agent",
        input={"message": "Where is my order?"},
        agent_version="v1.0.0",
        user_id="u-1",          # anything else becomes run metadata
    ) as trace:
        order = await get_order("A-1")
        trace.set_output({"message": format_reply(order["status"])})

    print(trace.status, len(trace.events), trace.uploaded)


asyncio.run(main())
```

The same block works synchronously — `with tracer.trace(...)` — and
`@tracer.tool` decorates sync and async functions alike. For an agent that
calls tools in parallel, see
[`examples/async_support_agent.py`](../../examples/async_support_agent.py).

`tracer.record_tool_call(name, arguments, response)` is still there for tools
you cannot decorate.

## Replay

Replay runs the agent's **own entry point** again — the same function that
records in production — while every `@tracer.tool` call is answered from a
recording instead of executing. Real tools never run during a replay.

```python
from agenttrace import AgentTracer, Recording

tracer = AgentTracer()


async def run_agent(request: dict) -> str:        # your normal entry point
    async with tracer.trace("support-agent", input=request) as trace:
        order = await get_order(request["order_id"])
        trace.set_output({"reply": order["status"]})
    return order["status"]


recording = await Recording.from_api(run_id)       # or Recording.from_trace(trace)
result = await tracer.replay(recording, run_agent, agent_version="v2.0.0")
```

- `agent_fn` is called with `recording.input` and must open its own
  `tracer.trace(...)`; it may be async or sync (a sync one runs in
  `asyncio.to_thread`). That trace carries `replay_of_run_id` and uploads as
  usual when `AGENTTRACE_PROJECT_ID` is set.
- `agent_version=` overrides the version on the replay's trace.
- The agent's own exceptions are captured in `result.error`, not raised.

Loading a recording:

| | |
| --- | --- |
| `Recording.from_trace(trace)` | A trace recorded in this process — tests and demos |
| `Recording.from_payload(dict)` | A `RunIngest`-shaped dict, e.g. `build_payload(trace)` |
| `await Recording.from_api(run_id, config=None)` | Fetch from the API; `from_api_sync` is the blocking variant |

### How calls are matched

A live call is matched against the **unused** recorded calls of the same
tool: first **exact** (canonical JSON of the arguments), then **normalized**
(strings stripped, `2.0` → `2`, `None`-valued keys dropped; list order and
case are kept). Among equal candidates the earliest recorded wins, and each
recorded call answers once — so three identical polling calls get the three
recorded answers in order, and parallel calls each get their own.

| The match | What the tool call does |
| --- | --- |
| Recorded response | Returns a copy of it |
| Recorded builtin error (`TimeoutError`, `KeyError`, …) | Raises the same type |
| Recorded other error | Raises `ReplayedToolError(error_type, message)` |
| Recorded call with no result | Raises `ReplayedToolError` |
| Nothing matches | Raises `UnmatchedToolCall(tool_name, arguments)` |

### The result

`ReplayResult` reports facts, not a verdict: `status`, `output` (the replay
trace's, comparable with `recording.output`), `return_value`, `error`,
`matches` (per live call: tool, tier `exact`/`normalized`/`unmatched`, new and
recorded `call_id` and arguments), `unused` (recorded calls never made),
`summary` counts, and `trace`, the replay's own trace. An agent that opens no
trace, or more than one, is reported in `error`.

### Replay raises; recording does not

Recording never raises into your code. Replay is test tooling you invoke on
purpose, so it fails loudly:

| Exception | When |
| --- | --- |
| `RecordingNotFound` | `from_api` got a 404 (subclass of `AgentTraceAPIError`) |
| `AgentTraceAPIError` | Any other fetch failure; `.status` is the HTTP status or None |
| `ReplayError` | `replay` called inside another replay; a payload with no run id |
| `UnmatchedToolCall` | Raised inside the agent for a call nothing matches |
| `ReplayedToolError` | Raised inside the agent for a recorded non-builtin error |

### Replay limitations

- **Only `@tracer.tool` functions are replayable.** A call recorded with
  `record_tool_call` has already run by the time the SDK sees it; during replay
  it is recorded as usual but not answered, and its recorded counterpart is
  reported unused.
- **The agent's own LLM calls run live** unless they are wrapped as tools.
- **The agent gets the recorded input.** A non-dict input was stored as
  `{"value": ...}` and is passed that way.
- **Recorded errors keep only a type name and message** — no traceback,
  attributes or chain.

## Comparison

`compare` turns a replay into a verdict. It is deterministic — no network, no
LLM, no clock — so the same recording and replay always give the same report.

```python
from agenttrace import ComparisonPolicy, compare

result, report = await tracer.replay_and_compare(recording, run_agent)
# or, from a result you already have:
report = compare(recording, result, policy=None)

report.verdict            # "pass" or "fail"
report.passed             # verdict == "pass"
report.findings           # tuple of Finding(code, severity, message, details)
report.counts             # {"by_severity": {...}, "by_code": {...}}
print(report.format())    # verdict line, then one line per finding
report.to_dict()          # JSON-serialisable, stable key order
```

Comparison reads what replay already decided — which call matched which, at
which tier, and what went unused — and never re-matches, so the two cannot
disagree about what "the same call" means.

| Code | Default | Meaning |
| --- | --- | --- |
| `AGENT_ERROR` | error | The agent raised during the replay (`result.error`) |
| `STATUS_CHANGED` | error | Recording and replay ended in different statuses |
| `MISSING_TOOL_CALL` | error | A recorded call the replay never made — a skipped step |
| `UNEXPECTED_TOOL_CALL` | error | A live call that matched nothing recorded |
| `ARGUMENTS_NORMALIZED` | warning | Matched only after normalization; arguments not identical |
| `TOOL_ORDER_CHANGED` | warning | Matched calls ran in a different order; one finding per point where the order went backwards |
| `OUTPUT_MISSING` | error | One side has an output and the other does not |
| `OUTPUT_STRUCTURE_CHANGED` | error | An output key added or removed, a type, number or boolean changed, a list length changed |
| `OUTPUT_TEXT_CHANGED` | warning | Only the wording of a string in the output differs |

The verdict is `fail` if any finding has severity `error`. Outputs are diffed
after the same `normalize` matching uses, so surrounding whitespace, `2` vs
`2.0` and a `None`-valued key vs a missing one are not reported at all.

`OUTPUT_TEXT_CHANGED` is a warning by default: exact text equality is brittle
for agents that answer in natural language, and deciding whether two wordings
mean the same thing is the planned semantic layer's job. Raise it to `error`
if your agent's output must match word for word.

### Policy

```python
policy = ComparisonPolicy(
    severity_overrides={"OUTPUT_TEXT_CHANGED": "error", "TOOL_ORDER_CHANGED": "info"},
    ignore_paths=["timestamp", "reply.generated_at", "items.*.id"],
)
```

- `severity_overrides` — code → `"error"` / `"warning"` / `"info"`. An
  unknown code or severity raises `ValueError` when the policy is built.
- `ignore_paths` — dot paths into the output that are expected to vary. A
  difference at the path or anywhere beneath it is reported as `info`, so it
  never fails the verdict but stays visible. `*` matches any list index
  (`items.*.id`); list indexes are numbers in a path (`items.0.id`). A dict key
  containing a dot cannot be addressed.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENTTRACE_API_URL` | `http://localhost:8000` | Where the API lives |
| `AGENTTRACE_API_KEY` | _unset_ | Optional until authentication ships |
| `AGENTTRACE_PROJECT_ID` | _unset_ | The project runs are uploaded to |
| `AGENTTRACE_TIMEOUT` | `5` | Seconds to wait for one upload |

**Uploading is opt-in.** Without `AGENTTRACE_PROJECT_ID` the SDK records
traces in memory and never opens a socket, so it is safe to import in tests
and offline. An invalid `AGENTTRACE_TIMEOUT` falls back to the default rather
than failing.

## How a run is recorded

A whole run is buffered in memory and uploaded in **one request** when the
block exits, to `POST /api/v1/projects/{project_id}/runs/ingest`. The API
writes the run and all its events in a single transaction, so a trace is
stored whole or not at all — a half-stored trace would look to replay like a
complete recording of an agent that stopped early.

Events are recorded in order: `agent_start`, then a `tool_call` and a
`tool_response` (or an `error`) per tool, then `agent_end`. A call and the
response that answered it share a `call_id`, which is what lets parallel tool
calls be paired back up.

Each event is **snapshotted as it is recorded** — a JSON round trip that
detaches it from the agent's own objects. Mutating a value a tool returned
does not rewrite the recording, which is what makes a trace usable as a replay
fixture. `trace.tool_calls` holds those same snapshots, so the call and its
events can never disagree.

`tracer.completed_traces` keeps only the **last 100** traces. A long-running
server records one per request, and an unbounded list would be a memory leak
that only shows up in production.

## Recording never breaks the host application

The SDK is imported into someone else's agent process, so it is built not to
change how that process behaves:

- Tool results and exceptions pass through **unchanged** — a decorated tool
  re-raises the original exception object, after recording it.
- Failures to record or upload are logged to the `agenttrace` logger and
  swallowed. A dead API costs a trace, never a request.
- `KeyboardInterrupt` and `asyncio.CancelledError` always propagate.
- Uploads are bounded by `AGENTTRACE_TIMEOUT`, and an async run sends from a
  worker thread so the event loop is never stalled.
- No runtime dependencies. The transport is `urllib` from the standard
  library, so the SDK cannot constrain the host's dependency tree.

To see what it is doing:

```python
import logging
logging.getLogger("agenttrace").setLevel(logging.DEBUG)
```

## Known limitations

- **A hard process kill loses the in-flight run.** Nothing is sent until the
  run ends, so `SIGKILL`, a power loss or a crashed interpreter takes the whole
  trace with it. Incremental upload would trade that for a request per event
  and partially recorded runs.
- **`AGENTTRACE_TIMEOUT` bounds each socket operation, not the whole request.**
  It is passed to `urllib`, where it is a per-operation socket timeout, so a
  server that keeps trickling bytes can hold the upload open for longer than
  the configured value.
- **Context propagates into `asyncio.to_thread`, but not into
  `loop.run_in_executor` or a raw `threading.Thread`.** The active trace lives
  in a `ContextVar`, and only `to_thread` copies the current context into the
  worker. A tool invoked from a raw thread or an executor sees no active trace
  and is **not recorded** — it still runs and returns normally. Use
  `asyncio.to_thread` for synchronous tools.
- **Values that are not JSON-serialisable are recorded as their string form.**
  `NaN`, `Infinity`, circular references and objects JSON cannot express
  degrade to a `repr`, with a warning. The recording is lossy for that value
  rather than missing.

## Scope

Recording, upload, replay and deterministic comparison are implemented.
Semantic comparison, regression suites and evaluation are later milestones.
