"""Domain errors raised by the service layer.

Services know nothing about HTTP. They raise these, and `app/main.py`
registers the handlers that turn them into responses. Three classes, not a
framework: one for "it isn't there", one for "it is, but not like that", and
one for "the body points at something it may not".
"""

from __future__ import annotations

from typing import Any


class AgentTraceError(Exception):
    """Base class for errors the API knows how to answer."""

    detail: str = "Unexpected error."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.detail
        super().__init__(self.detail)


class NotFoundError(AgentTraceError):
    """A referenced entity does not exist."""

    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(f"{resource} {identifier} does not exist.")


class ConflictError(AgentTraceError):
    """The request is valid but conflicts with the current state."""


class UnprocessableError(AgentTraceError):
    """The body is well-formed but refers to something it may not.

    Pydantic rejects what it can see in the payload alone. Some rules need the
    database -- "this id must name a run in the same project" -- and those
    fail with this, so the caller gets the same 422 it would for any other
    invalid field rather than a 404 that reads as "your URL is wrong".
    """

    def __init__(self, field: str, detail: str) -> None:
        self.field = field
        super().__init__(detail)
