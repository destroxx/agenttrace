"""API contracts for runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.schemas.event import EventCreate

# An upper bound on one upload, so a runaway agent cannot post an unbounded
# payload. Well above any realistic trace length.
MAX_INGEST_EVENTS = 10_000


class RunCreate(BaseModel):
    """Request body for starting a run.

    Status is not accepted here: a run always begins as `running`. Only the
    completion endpoint may move it out of that state.
    """

    agent_name: str = Field(min_length=1, max_length=255, examples=["support-agent"])
    agent_version: str | None = Field(default=None, max_length=64, examples=["v1.2.0"])
    input: dict[str, Any] = Field(examples=[{"message": "Where is my order?"}])


class RunComplete(BaseModel):
    """Request body for finishing a run."""

    output: dict[str, Any] | None = Field(
        default=None,
        examples=[{"message": "Your order is arriving tomorrow."}],
    )
    status: Literal["completed", "failed"] = "completed"


class RunIngest(RunCreate):
    """Request body for uploading one already-finished run.

    Subclasses `RunCreate` so the agent fields carry exactly the same
    constraints the incremental path enforces; drift between the two would let
    a run in through one door that the other rejects.

    An ingested run is finished by definition -- the SDK buffers the whole
    execution and uploads it once the agent has stopped -- so the client also
    supplies the timestamps it observed, rather than the API inventing them at
    receipt time.
    """

    id: uuid.UUID = Field(
        description=(
            "Client-generated run id. Makes the upload safe to retry: a second "
            "upload of the same run conflicts instead of duplicating it."
        ),
    )
    output: dict[str, Any] | None = Field(
        default=None,
        examples=[{"message": "Your order is arriving tomorrow."}],
    )
    status: Literal["completed", "failed"] = "completed"
    started_at: AwareDatetime = Field(
        description="When the agent started, as observed by the client."
    )
    completed_at: AwareDatetime = Field(
        description="When the agent stopped, as observed by the client."
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Free-form run context: user id, environment, git SHA.",
        examples=[{"user_id": "u-1", "environment": "staging"}],
    )
    events: list[EventCreate] = Field(
        default_factory=list,
        max_length=MAX_INGEST_EVENTS,
        description="The whole trace, in one payload.",
    )
    replay_of_run_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Set when this run was produced by replaying a recording: the id of "
            "that recording. It must be a run in the same project."
        ),
    )

    @model_validator(mode="after")
    def _check_timeline(self) -> RunIngest:
        """A run cannot finish before it started."""
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not be earlier than started_at.")
        return self

    @model_validator(mode="after")
    def _check_sequences_are_unique(self) -> RunIngest:
        """Reject the collision here rather than letting the database find it.

        The unique constraint would catch it, but only after a failed insert,
        and the caller would learn less about which position was duplicated.
        """
        seen: set[int] = set()
        for event in self.events:
            if event.sequence in seen:
                raise ValueError(
                    f"Duplicate sequence {event.sequence} in events; "
                    "each event must claim a distinct position."
                )
            seen.add(event.sequence)
        return self


class RunResponse(BaseModel):
    """A run as returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    project_id: uuid.UUID
    agent_name: str
    agent_version: str | None
    input: dict[str, Any]
    output: dict[str, Any] | None
    # Read from the ORM's `run_metadata`, never from `metadata`: on a mapped
    # class that attribute is SQLAlchemy's MetaData registry, so validating
    # against the field name would serialise the schema instead of the data.
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias="run_metadata"
    )
    status: str
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    replay_of_run_id: uuid.UUID | None = None


class RunSummary(RunResponse):
    """A run as it appears in a list: the run, plus what a table of runs shows.

    Only list items carry these. They are computed by the list query itself;
    the single-run endpoint returns the events and the report separately, so
    repeating them there would be a second source for the same facts.
    """

    event_count: int = Field(description="How many events the run recorded.")
    duration_ms: int | None = Field(
        description=(
            "completed_at - started_at, from the client's clock; null while running."
        )
    )
    verdict: Literal["pass", "fail"] | None = Field(
        description="The verdict of this run's comparison report; null when it has none."
    )
