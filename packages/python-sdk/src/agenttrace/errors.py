"""Exceptions the SDK raises on purpose.

Recording never raises into user code. Replay is different: it is test
tooling a developer invokes deliberately, so misuse, a recording that cannot
be fetched, and a tool call the recording cannot answer all fail loudly with
one of these rather than being logged and swallowed.
"""

from __future__ import annotations

from typing import Any


class AgentTraceAPIError(Exception):
    """The API could not be reached, or answered with something unusable.

    `status` is the HTTP status when there was a response, and None when the
    request never got one (connection refused, timeout, a body that is not
    JSON).
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class RecordingNotFound(AgentTraceAPIError):
    """The API has no run with the requested id.

    A subclass of `AgentTraceAPIError` so one `except` covers every way a
    fetch can fail, while a test can still tell "wrong id" from "API down".
    """


class ReplayError(Exception):
    """Replay was set up or used in a way it does not support.

    Nesting one replay inside another, or a recording payload that is missing
    the fields a replay needs.
    """


class UnmatchedToolCall(Exception):
    """A tool was called during replay and no recorded call matches it.

    Raised inside the agent, in place of running the real tool, because there
    is no recorded answer to give and calling production is exactly what
    replay exists to avoid. The call still appears in the replay result as
    "unmatched".
    """

    def __init__(self, tool_name: str, arguments: dict[str, Any]) -> None:
        super().__init__(
            f"no unused recorded call to {tool_name!r} matches arguments {arguments!r}"
        )
        self.tool_name = tool_name
        self.arguments = arguments


class ReplayedToolError(Exception):
    """A recorded tool failure that cannot be rebuilt as its original type.

    The recording stores an error as its type name and message, not the
    exception object. Builtin exceptions are rebuilt as themselves; anything
    else -- a library's or the user's own exception class -- is raised as this,
    carrying the recorded name. Also raised when the recording holds a call
    with no recorded result at all.
    """

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(f"{error_type}: {message}")
        self.error_type = error_type
        self.message = message
