"""API contracts for comparison reports.

The report itself is produced by the SDK (`ComparisonReport.to_dict()`); the
API stores it and hands it back. The request schema pins down the parts the
API relies on -- the verdict, and which runs the report is about -- and lets
anything else through, so a newer SDK adding a field to its report does not
have its uploads rejected by an older API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Generous, like MAX_INGEST_EVENTS: a bound on one upload, not a real limit.
MAX_FINDINGS = 10_000

Verdict = Literal["pass", "fail"]
Severity = Literal["error", "warning", "info"]


class FindingPayload(BaseModel):
    """One finding, as the SDK's `Finding.to_dict()` writes it."""

    model_config = ConfigDict(extra="allow")

    code: str = Field(min_length=1, max_length=64, examples=["MISSING_TOOL_CALL"])
    severity: Severity
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ComparisonCounts(BaseModel):
    """Finding counts per severity and per code."""

    model_config = ConfigDict(extra="allow")

    by_severity: dict[str, int] = Field(default_factory=dict)
    by_code: dict[str, int] = Field(default_factory=dict)


class ComparisonCreate(BaseModel):
    """Request body for storing a report: `ComparisonReport.to_dict()`."""

    model_config = ConfigDict(extra="allow")

    verdict: Verdict
    recording_run_id: uuid.UUID
    replay_run_id: uuid.UUID = Field(
        description="Must equal the run id in the URL; the report is stored against it."
    )
    counts: ComparisonCounts = Field(default_factory=ComparisonCounts)
    findings: list[FindingPayload] = Field(default_factory=list, max_length=MAX_FINDINGS)

    @model_validator(mode="after")
    def _check_verdict_matches_findings(self) -> ComparisonCreate:
        """The stored verdict is shown without re-reading the findings, so it must agree.

        The SDK fails a report exactly when a finding has severity "error".
        A report claiming otherwise was edited or produced by something else,
        and a dashboard showing PASS over a list of errors would be worse than
        rejecting it.
        """
        has_error = any(finding.severity == "error" for finding in self.findings)
        if has_error != (self.verdict == "fail"):
            raise ValueError(
                f"verdict {self.verdict!r} disagrees with the findings: the verdict is "
                "'fail' exactly when some finding has severity 'error'."
            )
        return self


class ComparisonResponse(BaseModel):
    """A stored report."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    replay_run_id: uuid.UUID
    recording_run_id: uuid.UUID
    verdict: Verdict
    report: dict[str, Any]
    created_at: datetime


class ComparisonSummary(BaseModel):
    """A report in a list: its verdict and counts, without the findings."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    replay_run_id: uuid.UUID
    recording_run_id: uuid.UUID
    verdict: Verdict
    counts: dict[str, Any] | None = Field(
        default=None, description="The report's `counts`, read out of the stored JSON."
    )
    created_at: datetime
