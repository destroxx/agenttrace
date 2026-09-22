"""Record the support agent once, then replay three versions of it against that recording.

Scripted -- no LLM, no API key. Every tool body in `async_support_agent`
counts its real executions, and this demo checks that the count does not move
while replaying: the tools are answered from the recording, never run.

    v1  the unchanged agent          -> every call matches, nothing unused
    v2  skips a delivery lookup      -> that recorded call is reported unused
    v3  looks orders up in lowercase -> those calls are reported unmatched

Run from the repo root with the workspace virtualenv:

    .venv/bin/python examples/replay_demo.py

Without AGENTTRACE_PROJECT_ID everything stays in memory. With it (and the API
running), the recording is uploaded, fetched back with `Recording.from_api`,
and each replay is uploaded pointing at it through `replay_of_run_id`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agenttrace import Recording, ReplayResult
from async_support_agent import (
    REAL_CALLS,
    REQUEST,
    format_reply,
    get_customer,
    get_delivery_status,
    get_order,
    run_agent,
    tracer,
)

# --- the three versions under test ------------------------------------------
#
# Each is a complete entry point, as a customer would ship it: it opens its own
# trace and calls the same tools. Only v1 is the code that was recorded.


async def run_agent_v2(request: dict) -> str:
    """Skips the delivery lookup for orders still processing -- it already knows."""
    async with tracer.trace("support-agent", input=request, agent_version="v2.0.0") as trace:
        customer = await get_customer(request["customer_id"])
        orders = await asyncio.gather(*(get_order(i) for i in request["order_ids"]))
        lines = []
        for order in orders:
            if order["status"] == "processing":
                status = "not yet dispatched"
            else:
                status = await get_delivery_status(order["id"])
            lines.append(f"{order['item']} ({order['id']}): {status}")
        reply = format_reply(customer["name"], lines)
        trace.set_output({"message": reply})
    return reply


async def run_agent_v3(request: dict) -> str:
    """A regression: order ids are lowercased before the lookup."""
    async with tracer.trace("support-agent", input=request, agent_version="v3.0.0") as trace:
        customer = await get_customer(request["customer_id"])
        orders = await asyncio.gather(*(get_order(i.lower()) for i in request["order_ids"]))
        lines = [f"{o['item']}: {await get_delivery_status(o['id'])}" for o in orders]
        reply = format_reply(customer["name"], lines)
        trace.set_output({"message": reply})
    return reply


VERSIONS = [
    ("v1", "unchanged", run_agent),
    ("v2", "skips a delivery lookup", run_agent_v2),
    ("v3", "lowercases order ids", run_agent_v3),
]

# --- rendering ---------------------------------------------------------------

ARGS_WIDTH = 34


def _arguments(arguments: dict[str, Any] | None) -> str:
    if arguments is None:
        return "—"
    text = ", ".join(f"{key}={value!r}" for key, value in sorted(arguments.items()))
    return text if len(text) <= ARGS_WIDTH else text[: ARGS_WIDTH - 1] + "…"


def _rows(result: ReplayResult) -> list[tuple[str, str, str, str]]:
    """One row per recorded or replayed call, in recorded order.

    Matched and unused calls sit at their recorded position; an unmatched
    call has none, so it goes straight after whatever the agent called before
    it.
    """
    keyed: list[tuple[float, tuple[str, str, str, str]]] = []
    position = -1.0
    for match in result.matches:
        if match.recorded_sequence is not None:
            position = float(match.recorded_sequence)
        else:
            position += 0.001
        keyed.append(
            (
                position,
                (
                    match.tool_name,
                    _arguments(match.recorded_arguments),
                    _arguments(match.new_arguments),
                    match.tier,
                ),
            )
        )
    for unused in result.unused:
        keyed.append(
            (
                float(unused.recorded_sequence),
                (unused.tool_name, _arguments(unused.arguments), "—", "unused"),
            )
        )
    return [row for _, row in sorted(keyed, key=lambda item: item[0])]


def _print_table(rows: list[tuple[str, str, str, str]]) -> None:
    header = ("tool", "recorded arguments", "new agent's arguments", "outcome")
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(4)]
    for row in [header, tuple("─" * w for w in widths), *rows]:
        print("  " + "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())


def _print_result(label: str, about: str, result: ReplayResult, recording: Recording) -> None:
    print(f"\n{label} — {about}")
    _print_table(_rows(result))
    s = result.summary
    same = "same as recording" if result.output == recording.output else "differs from recording"
    print(
        f"  {label}: {s.exact} exact · {s.normalized} normalized · {s.unmatched} unmatched · "
        f"{s.unused} unused · status {result.status} · output {same}"
    )
    if result.error:
        print(f"  error: {result.error['type']}: {result.error['message']}")
    if result.trace is not None:
        uploaded = f", uploaded {result.trace.uploaded}" if tracer.config.upload_enabled else ""
        print(f"  replay run {result.trace.id} (replay_of {result.trace.replay_of_run_id}{uploaded})")


async def main() -> None:
    live = tracer.config.upload_enabled
    print(f"mode: {'live, via ' + tracer.config.api_url if live else 'in memory'}")

    await run_agent(REQUEST)
    recorded_trace = tracer.completed_traces[-1]
    recorded_executions = sum(REAL_CALLS.values())
    print(f"recorded run {recorded_trace.id}: {recorded_executions} real tool executions")
    if live:
        if not recorded_trace.uploaded:
            raise SystemExit("the recording did not upload; is the API running?")
        recording = await Recording.from_api(recorded_trace.id, tracer.config)
        print(f"fetched recording {recording.run_id} back from the API")
    else:
        recording = Recording.from_trace(recorded_trace)

    REAL_CALLS.clear()
    for label, about, agent in VERSIONS:
        result = await tracer.replay(recording, agent)
        _print_result(label, about, result, recording)

    executed = sum(REAL_CALLS.values())
    print(f"\nreal tool executions during all three replays: {executed}")
    assert executed == 0, f"replay ran real tools: {dict(REAL_CALLS)}"


if __name__ == "__main__":
    asyncio.run(main())
