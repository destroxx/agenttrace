"""Business logic for comparison reports."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Row, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comparison import Comparison
from app.models.project import Project
from app.models.run import Run
from app.schemas.comparison import ComparisonCreate
from app.services.exceptions import ConflictError, NotFoundError, UnprocessableError
from app.services.pagination import Pagination
from app.services.runs import violated_constraint


def _foreign_recording(run_id: uuid.UUID, project_id: uuid.UUID) -> UnprocessableError:
    return UnprocessableError(
        "recording_run_id",
        f"recording_run_id {run_id} is not a run in project {project_id}.",
    )


class ComparisonService:
    """Stores the reports the SDK uploads and reads them back.

    The API never computes a verdict. Comparison runs in the SDK, next to the
    agent code, because CI needs the answer locally; storing the report here
    is only so it can be looked at later.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, replay_run_id: uuid.UUID, data: ComparisonCreate) -> Comparison:
        """Store the report for one replay run.

        Reports are immutable, like the runs they describe: a second report for
        the same run conflicts rather than replacing the first, so a verdict
        someone has already seen cannot quietly change underneath them. The SDK
        treats that conflict as "already stored", which makes its upload safe
        to retry.

        The recording must be in the replay's project -- the same rule ingest
        applies to `replay_of_run_id`, for the same reason -- and the run must
        be a replay of exactly that recording. A plain recording has no
        report: a verdict on a run that replayed nothing, or one "about"
        itself, would put a PASS/FAIL badge on a run that was never compared.
        An unknown recording and a foreign one get the same answer, so the
        error does not reveal which run ids exist elsewhere.
        """
        replay = await self._session.get(Run, replay_run_id)
        if replay is None:
            raise NotFoundError("Run", replay_run_id)
        if data.replay_run_id != replay_run_id:
            raise UnprocessableError(
                "replay_run_id",
                f"replay_run_id {data.replay_run_id} does not match run {replay_run_id} "
                "in the URL.",
            )
        recording = await self._session.get(Run, data.recording_run_id)
        if recording is None or recording.project_id != replay.project_id:
            raise _foreign_recording(data.recording_run_id, replay.project_id)
        if replay.replay_of_run_id is None:
            raise UnprocessableError(
                "recording_run_id",
                f"run {replay_run_id} is not a replay, so it has no recording "
                f"{data.recording_run_id} to be compared with.",
            )
        if replay.replay_of_run_id != recording.id:
            raise UnprocessableError(
                "recording_run_id",
                f"run {replay_run_id} is a replay of {replay.replay_of_run_id}, "
                f"not of {data.recording_run_id}.",
            )

        comparison = Comparison(
            replay_run_id=replay_run_id,
            recording_run_id=data.recording_run_id,
            verdict=data.verdict,
            report=data.model_dump(mode="json"),
        )
        self._session.add(comparison)
        try:
            await self._session.flush()
            await self._session.refresh(comparison)
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            violated = violated_constraint(exc)
            if violated == "uq_comparisons_replay_run_id":
                raise ConflictError(
                    f"Run {replay_run_id} already has a comparison report."
                ) from exc
            # Either run was deleted between the checks above and the insert;
            # answer as if the checks had seen it gone, like ingest does.
            if violated == "fk_comparisons_recording_run_id_runs":
                raise _foreign_recording(data.recording_run_id, replay.project_id) from exc
            if violated == "fk_comparisons_replay_run_id_runs":
                raise NotFoundError("Run", replay_run_id) from exc
            raise
        return comparison

    async def get_for_run(self, run_id: uuid.UUID) -> Comparison:
        """Return the report for a replay run.

        Two different 404s: the run does not exist, or it exists and has no
        report -- which is the normal state of a recording, and of a replay
        whose report was never uploaded.
        """
        if await self._session.get(Run, run_id) is None:
            raise NotFoundError("Run", run_id)
        comparison = await self._session.scalar(
            select(Comparison).where(Comparison.replay_run_id == run_id)
        )
        if comparison is None:
            raise NotFoundError("Comparison for run", run_id)
        return comparison

    async def list_for_project(
        self, project_id: uuid.UUID, pagination: Pagination
    ) -> tuple[Sequence[Row], int]:
        """One page of a project's reports, newest first, without their findings.

        A report belongs to the project of its replay run. Only the counts are
        read out of the JSON, so a page of large reports stays a small response.
        """
        if await self._session.get(Project, project_id) is None:
            raise NotFoundError("Project", project_id)

        in_project = Run.project_id == project_id
        total = await self._session.scalar(
            select(func.count())
            .select_from(Comparison)
            .join(Run, Run.id == Comparison.replay_run_id)
            .where(in_project)
        )
        result = await self._session.execute(
            select(
                Comparison.id,
                Comparison.replay_run_id,
                Comparison.recording_run_id,
                Comparison.verdict,
                Comparison.report["counts"].label("counts"),
                Comparison.created_at,
            )
            .join(Run, Run.id == Comparison.replay_run_id)
            .where(in_project)
            .order_by(Comparison.created_at.desc(), Comparison.id)
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        return result.all(), int(total or 0)
