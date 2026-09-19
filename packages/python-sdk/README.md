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
fixture. `ToolCall.response` is the exception: it holds the live object.

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

Recording and upload are implemented. Replay, comparison and evaluation are
later milestones.
