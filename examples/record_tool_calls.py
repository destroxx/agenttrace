"""Minimal AgentTrace SDK usage.

Run from the repo root with the workspace virtualenv:

    .venv/bin/python examples/record_tool_calls.py
"""

from __future__ import annotations

from agenttrace import AgentTracer


def fake_search(query: str) -> list[str]:
    """Stands in for a real tool the agent would call."""
    return [f"result for {query}"]


def main() -> None:
    tracer = AgentTracer()
    print(f"configured against {tracer.config.api_url}")

    with tracer.trace("demo-agent", user="example-user") as trace:
        query = "running shoes"
        tracer.record_tool_call("search", {"q": query}, response=fake_search(query))
        tracer.record_tool_call("add_to_cart", {"sku": "SKU-1"}, response={"ok": True})

    print(f"trace {trace.id} recorded {len(trace.tool_calls)} tool call(s)")
    for call in trace.tool_calls:
        print(f"  - {call.name}({call.arguments}) -> {call.response}")
    print(f"open: {trace.is_open}")


if __name__ == "__main__":
    main()
