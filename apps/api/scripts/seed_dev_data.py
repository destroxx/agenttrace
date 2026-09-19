"""Seed the database with one realistic trace, for manual API poking.

Creates a project, a run, three events and then completes the run -- the whole
Phase 2 workflow in one command:

    python -m scripts.seed_dev_data

It goes through the service layer rather than raw SQL so that seeding exercises
the same code paths the API does.
"""

from __future__ import annotations

import asyncio

from app.db.session import dispose_engine, get_sessionmaker
from app.schemas.event import EventCreate
from app.schemas.project import ProjectCreate
from app.schemas.run import RunComplete, RunCreate
from app.services.events import EventService
from app.services.projects import ProjectService
from app.services.runs import RunService

TRACE = [
    EventCreate(sequence=1, event_type="agent_start"),
    EventCreate(
        sequence=2,
        event_type="tool_call",
        call_id="call_abc123",
        tool_name="get_order",
        arguments={"order_id": "12345"},
    ),
    EventCreate(
        sequence=3,
        event_type="tool_response",
        call_id="call_abc123",
        tool_name="get_order",
        response={"order_id": "12345", "status": "in_transit", "eta": "2026-09-19"},
        duration_ms=42,
    ),
]


async def seed() -> None:
    """Write one complete project -> run -> events -> completion trace."""
    async with get_sessionmaker()() as session:
        project = await ProjectService(session).create(
            ProjectCreate(
                name="Customer Support Agent",
                description="Regression tests for our support agent",
            )
        )
        run = await RunService(session).create(
            project.id,
            RunCreate(
                agent_name="support-agent",
                agent_version="v1.2.0",
                input={"message": "Where is my order?"},
            ),
        )
        for event in TRACE:
            await EventService(session).create(run.id, event)

        completed = await RunService(session).complete(
            run.id,
            RunComplete(
                output={"message": "Your order is arriving tomorrow."},
                status="completed",
            ),
        )

    print(f"project  {project.id}  {project.name}")
    print(f"run      {run.id}  status={completed.status}")
    print(f"events   {len(TRACE)} written (sequences 1-{len(TRACE)})")
    print()
    print("Inspect it:")
    print(f"  curl -s localhost:8000/api/v1/projects/{project.id}")
    print(f"  curl -s localhost:8000/api/v1/projects/{project.id}/runs")
    print(f"  curl -s localhost:8000/api/v1/runs/{run.id}")
    print(f"  curl -s localhost:8000/api/v1/runs/{run.id}/events")


def main() -> None:
    """Entry point."""

    async def _run() -> None:
        try:
            await seed()
        finally:
            await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
