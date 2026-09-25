"""Business logic for projects."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.run import Run
from app.schemas.project import ProjectCreate
from app.services.exceptions import NotFoundError
from app.services.pagination import Pagination


class ProjectService:
    """Creates and reads projects."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: ProjectCreate) -> Project:
        """Persist a new project."""
        project = Project(name=data.name, description=data.description)
        self._session.add(project)
        await self._session.flush()
        await self._session.refresh(project)
        await self._session.commit()
        return project

    async def get(self, project_id: uuid.UUID) -> Project:
        """Return one project, or raise `NotFoundError`."""
        project = await self._session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project", project_id)
        return project

    async def list(
        self, pagination: Pagination
    ) -> tuple[Sequence[Row[tuple[Project, int, datetime | None]]], int]:
        """Return one page of projects, newest first, with the total count.

        Each row is `(project, run_count, last_run_at)`, computed in the same
        query as correlated subqueries over the runs' (project_id, created_at)
        index -- one query for the page, not one per project.
        """
        total = await self._session.scalar(
            select(func.count()).select_from(Project)
        )
        run_count = (
            select(func.count(Run.id))
            .where(Run.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        last_run_at = (
            select(func.max(Run.created_at))
            .where(Run.project_id == Project.id)
            .correlate(Project)
            .scalar_subquery()
        )
        result = await self._session.execute(
            select(Project, run_count.label("run_count"), last_run_at.label("last_run_at"))
            .order_by(Project.created_at.desc(), Project.id)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        return result.all(), int(total or 0)
