"""Domain errors raised by the service layer.

Services know nothing about HTTP. They raise these, and `app/main.py`
registers the handlers that turn them into responses. Five classes, not a
framework: one for "it isn't there", one for "it is, but not like that", one
for "the body points at something it may not", one for "who are you?" and one
for "not with that key".
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


class AuthenticationError(AgentTraceError):
    """The request carries no API key, or one that is unknown or revoked.

    One message for all three, so a caller probing keys learns nothing about
    which keys exist or once existed.
    """

    detail = "A valid API key is required: send it as 'Authorization: Bearer <key>'."


class PermissionDeniedError(AgentTraceError):
    """The key is valid, but not for what it was used on."""
