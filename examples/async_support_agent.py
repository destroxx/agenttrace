"""An async support agent, recorded end to end and uploaded in one request.

The agent is scripted — no LLM, no API key — so the interesting part is the
trace it produces: four tools, two of them called in parallel, and one run
uploaded when the block exits.

Run from the repo root with the workspace virtualenv:

    .venv/bin/python examples/async_support_agent.py

Set AGENTTRACE_PROJECT_ID (and AGENTTRACE_API_URL, if the API is not on
localhost:8000) to upload the run. Without them the trace stays in memory and
no HTTP request is made, so this example still works offline.
"""

from __future__ import annotations

import asyncio
import logging

from agenttrace import AgentTracer

tracer = AgentTracer()

CUSTOMERS = {"c-42": {"id": "c-42", "name": "Dana", "tier": "gold"}}
ORDERS = {
    "A-1": {"id": "A-1", "item": "Running shoes", "status": "shipped"},
    "B-2": {"id": "B-2", "item": "Wool socks", "status": "processing"},
}
DELIVERY = {"A-1": "arriving tomorrow", "B-2": "not yet dispatched"}


@tracer.tool
async def get_customer(customer_id: str) -> dict:
    """Look up a customer. The sleep stands in for a network round trip."""
    await asyncio.sleep(0.05)
    return CUSTOMERS[customer_id]


@tracer.tool
async def get_order(order_id: str) -> dict:
    """Look up one order."""
    await asyncio.sleep(0.05)
    return ORDERS[order_id]


@tracer.tool
async def get_delivery_status(order_id: str) -> str:
    """Look up where an order has got to."""
    await asyncio.sleep(0.05)
    return DELIVERY[order_id]


@tracer.tool
def format_reply(customer_name: str, lines: list[str]) -> str:
    """Compose the answer. Synchronous, to show both kinds of tool recorded."""
    body = "\n".join(f"  - {line}" for line in lines)
    return f"Hi {customer_name},\n{body}\n— Support"


async def handle_request(customer_id: str, order_ids: list[str]) -> str:
    """The agent's scripted reasoning."""
    customer = await get_customer(customer_id)

    # Two tools in flight at once: the whole point of recording a `call_id` is
    # that the responses can still be paired back to their calls afterwards.
    orders = await asyncio.gather(*(get_order(order_id) for order_id in order_ids))

    lines = []
    for order in orders:
        status = await get_delivery_status(order["id"])
        lines.append(f"{order['item']} ({order['id']}): {status}")

    return format_reply(customer["name"], lines)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    question = "Where are my two orders?"
    print(f"configured against {tracer.config.api_url}")
    print(f"upload enabled: {tracer.config.upload_enabled}")

    async with tracer.trace(
        "support-agent",
        input={"customer_id": "c-42", "message": question},
        agent_version="v1.0.0",
        environment="example",
    ) as trace:
        reply = await handle_request("c-42", ["A-1", "B-2"])
        trace.set_output({"message": reply})

    print()
    print(reply)
    print()
    print(f"trace id:  {trace.id}")
    print(f"status:    {trace.status}")
    print(f"events:    {len(trace.events)}")
    print(f"uploaded:  {trace.uploaded}")


if __name__ == "__main__":
    asyncio.run(main())
