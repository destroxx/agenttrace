"""Uploading finished traces, and comparison reports, to the AgentTrace API.

One request per run, at the end of the run: the API's ingest endpoint writes
the run and every event in a single transaction, so a trace is stored whole or
not at all. Nothing here ever raises into the host application -- a failed
upload costs a recording, and losing a recording is always cheaper than taking
down the agent that produced it.

Standard library only, by design: the SDK is imported into user processes and
must not drag an HTTP client into their dependency tree.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from agenttrace.config import TracerConfig
from agenttrace.models import RecordedEvent, Trace

logger = logging.getLogger("agenttrace")

INGEST_PATH = "/api/v1/projects/{project_id}/runs/ingest"
COMPARISON_PATH = "/api/v1/runs/{run_id}/comparison"

# The API answers 201 on success, and 409 when this run id -- or a report for
# this run -- is already stored.
_CREATED = 201
_CONFLICT = 409


def _isoformat(value: datetime) -> str:
    """Render a timestamp the way the API's `AwareDatetime` fields demand.

    A naive datetime is assumed to be UTC rather than rejected: the SDK's own
    clocks are timezone-aware, so a naive value can only have come from a
    caller overriding one, and dropping the whole upload over it would be a
    poor trade.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _event_payload(event: RecordedEvent) -> dict[str, Any]:
    """Shape one event into the API's `EventCreate` body.

    Built field by field rather than with `dataclasses.asdict`, which deep-
    copies what it walks: a tool response holding a database handle or a file
    object would raise there and cost the whole upload, and the copy would be
    wasted work even when it succeeds.
    """
    return {
        "sequence": event.sequence,
        "event_type": event.event_type,
        "call_id": event.call_id,
        "tool_name": event.tool_name,
        "arguments": event.arguments,
        "response": event.response,
        "duration_ms": event.duration_ms,
    }


def build_payload(trace: Trace) -> dict[str, Any]:
    """Shape a closed trace into the API's `RunIngest` body."""
    return {
        "id": trace.id,
        "agent_name": trace.name,
        "agent_version": trace.agent_version,
        "input": trace.input,
        "output": trace.output,
        "status": trace.status,
        "started_at": _isoformat(trace.started_at),
        # A trace is closed before it is uploaded, so `ended_at` is set. The
        # fallback keeps a hand-built trace from tripping the API's
        # completed_at >= started_at check with a null.
        "completed_at": _isoformat(trace.ended_at or trace.started_at),
        "metadata": dict(trace.metadata) if trace.metadata else None,
        "events": [_event_payload(event) for event in trace.events],
        "replay_of_run_id": trace.replay_of_run_id,
    }


def _response_body(exc: urllib.error.HTTPError) -> str:
    """Read an error response body, if the connection still has one to give."""
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:  # noqa: BLE001 - the body is a nicety; never worth raising for
        return ""


def upload(trace: Trace, config: TracerConfig) -> bool:
    """Send one finished trace. Returns whether it is now stored.

    Never raises: every failure path logs and answers False. A 409 answers
    True, because the run being already stored is the outcome the caller
    wanted -- that is the whole point of the client-generated run id.
    """
    if not config.upload_enabled:
        return False
    url = f"{config.api_url}{INGEST_PATH.format(project_id=config.project_id)}"
    return _post(url, lambda: build_payload(trace), config, f"trace {trace.id}")


def upload_comparison(report: Mapping[str, Any], config: TracerConfig) -> bool:
    """Send one comparison report, as `ComparisonReport.to_dict()` built it.

    Stored against its replay run, which must already be uploaded -- replay
    uploads the replay's trace before the agent returns, so by the time a
    report exists its run has been sent. The same rules as `upload`: never
    raises, and a 409 (a report already stored for that run) answers True,
    which makes a retried upload harmless. A report with no replay run has
    nothing to be stored against and is not sent.
    """
    if not config.upload_enabled:
        return False
    replay_run_id = report.get("replay_run_id")
    if not replay_run_id:
        logger.warning(
            "agenttrace: comparison report has no replay run id; not uploaded"
        )
        return False
    url = f"{config.api_url}{COMPARISON_PATH.format(run_id=replay_run_id)}"
    return _post(url, lambda: dict(report), config, f"comparison for run {replay_run_id}")


def _post(
    url: str,
    build: Callable[[], Any],
    config: TracerConfig,
    what: str,
) -> bool:
    """POST one JSON body to the API. Returns whether it is now stored; never raises.

    `build` is called in here, not by the caller, so a payload that fails to
    build is one more logged failure rather than an exception escaping.
    """
    try:
        # `default=str` keeps a datetime or a custom object in a tool payload
        # from failing the whole upload; a readable repr beats a lost trace.
        body = json.dumps(build(), default=str).encode("utf-8")
    except Exception as exc:
        logger.warning("agenttrace: could not serialise %s; not uploaded: %r", what, exc)
        logger.debug("agenttrace: serialisation failure detail", exc_info=True)
        return False

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if config.api_key:
        request.add_header("Authorization", f"Bearer {config.api_key}")

    try:
        with urllib.request.urlopen(
            request, timeout=config.timeout_seconds
        ) as response:
            if response.status == _CREATED:
                logger.debug("agenttrace: uploaded %s", what)
                return True
            logger.warning(
                "agenttrace: unexpected status %s uploading %s", response.status, what
            )
            return False
    except urllib.error.HTTPError as exc:
        if exc.code == _CONFLICT:
            logger.debug("agenttrace: %s is already stored", what)
            return True
        logger.warning(
            "agenttrace: upload of %s failed with status %s: %s",
            what,
            exc.code,
            _response_body(exc),
        )
        return False
    except Exception as exc:
        # Connection refused, DNS failure, timeout: the agent does not care.
        # One readable line by default and the traceback only under DEBUG -- an
        # unreachable API is an expected condition in someone else's process,
        # and a stack dump per run would be the SDK making itself the problem.
        logger.warning("agenttrace: upload of %s failed: %r", what, exc)
        logger.debug("agenttrace: upload failure detail", exc_info=True)
        return False
