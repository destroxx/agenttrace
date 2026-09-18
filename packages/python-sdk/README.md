# agenttrace (Python SDK)

Records AI-agent executions — tool calls and their responses — so they can be
replayed against a future version of the agent.

## Install (editable, for local development)

```bash
pip install -e "packages/python-sdk[dev]"
```

## Usage

```python
from agenttrace import AgentTracer

tracer = AgentTracer()  # reads AGENTTRACE_API_URL / AGENTTRACE_API_KEY

with tracer.trace("checkout-agent", user="u-1") as trace:
    tracer.record_tool_call("search", {"q": "shoes"}, response=["a", "b"])

print(len(trace.tool_calls))  # 1
```

## Scope

Traces are kept in memory. Uploading them to the AgentTrace API and replaying
them are later milestones; the surface above is meant to stay stable across
that change.
