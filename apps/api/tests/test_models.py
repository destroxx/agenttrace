"""Model-level tests: relationship navigation and delete cascades."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Event, Project, Run, RunStatus


async def _trace(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Write a project with one run and three out-of-order events.

    Returns ids rather than instances, and clears the identity map, so that
    what a test reads back really came from the database. Were the instances
    kept, their `events` collection would still hold the in-memory append
    order and the relationship's ORDER BY would never be exercised.
    """
    project = Project(name="Customer Support Agent")
    run = Run(
        project=project,
        agent_name="support-agent",
        agent_version="v1.2.0",
        input={"message": "Where is my order?"},
        status=RunStatus.RUNNING,
    )
    session.add(run)
    for sequence in (3, 1, 2):
        session.add(Event(run=run, sequence=sequence, event_type="tool_call"))
    await session.commit()

    identifiers = (project.id, run.id)
    session.expire_all()
    return identifiers


async def test_relationships_navigate_in_both_directions(
    db_session: AsyncSession,
) -> None:
    project_id, run_id = await _trace(db_session)

    project = await db_session.scalar(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.runs).selectinload(Run.events))
    )

    assert project is not None
    assert [run.id for run in project.runs] == [run_id]

    run = project.runs[0]
    assert run.project.id == project_id
    assert [event.sequence for event in run.events] == [1, 2, 3]
    assert run.events[0].run.id == run_id


async def test_run_events_relationship_is_ordered_by_sequence(
    db_session: AsyncSession,
) -> None:
    """Rule 2: the relationship itself carries the ordering."""
    _, run_id = await _trace(db_session)

    run = await db_session.scalar(
        select(Run).where(Run.id == run_id).options(selectinload(Run.events))
    )

    assert run is not None
    assert [event.sequence for event in run.events] == [1, 2, 3]


async def test_deleting_a_project_cascades_to_runs_and_events(
    db_session: AsyncSession,
) -> None:
    project_id, _ = await _trace(db_session)
    project = await db_session.get(Project, project_id)
    assert project is not None

    await db_session.delete(project)
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(Project)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Run)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Event)) == 0


async def test_deleting_a_run_cascades_to_events_but_spares_the_project(
    db_session: AsyncSession,
) -> None:
    _, run_id = await _trace(db_session)
    run = await db_session.get(Run, run_id)
    assert run is not None

    await db_session.delete(run)
    await db_session.commit()

    assert await db_session.scalar(select(func.count()).select_from(Project)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Run)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Event)) == 0


async def test_run_defaults_to_running(db_session: AsyncSession) -> None:
    run = Run(project=Project(name="Defaults"), agent_name="a", input={})
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    assert run.status == RunStatus.RUNNING
    assert run.is_terminal is False
    assert run.completed_at is None
    assert run.started_at is not None
    assert run.created_at is not None


async def test_terminal_states(db_session: AsyncSession) -> None:
    _, run_id = await _trace(db_session)
    run = await db_session.get(Run, run_id)
    assert run is not None

    assert run.is_terminal is False
    run.status = RunStatus.COMPLETED
    assert run.is_terminal is True
    run.status = RunStatus.FAILED
    assert run.is_terminal is True
