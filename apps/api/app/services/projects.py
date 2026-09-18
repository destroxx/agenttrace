"""Business logic for projects."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
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

    async def list(self, pagination: Pagination) -> tuple[list[Project], int]:
        """Return one page of projects, newest first, with the total count."""
        total = await self._session.scalar(
            select(func.count()).select_from(Project)
        )
        result = await self._session.scalars(
            select(Project)
            .order_by(Project.created_at.desc(), Project.id)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        return list(result), int(total or 0)
