"""SDK configuration.

Values are read from the environment so that host applications never need to
hardcode an endpoint or a key.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 5.0

ENV_API_URL = "AGENTTRACE_API_URL"
ENV_API_KEY = "AGENTTRACE_API_KEY"
ENV_PROJECT_ID = "AGENTTRACE_PROJECT_ID"
ENV_TIMEOUT = "AGENTTRACE_TIMEOUT"

logger = logging.getLogger("agenttrace")


def _timeout_from_env(raw: str | None) -> float:
    """Parse the upload timeout, falling back rather than failing.

    A malformed value in someone's deployment environment must not stop their
    agent from starting: tracing is never worth an outage, so a bad setting
    degrades to the default and says so in the log.
    """
    if raw is None or not raw.strip():
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "agenttrace: %s=%r is not a number; using %ss",
            ENV_TIMEOUT,
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "agenttrace: %s=%r must be a positive number; using %ss",
            ENV_TIMEOUT,
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS
    return value


@dataclass(frozen=True, slots=True)
class TracerConfig:
    """Connection settings for the AgentTrace backend."""

    api_url: str = DEFAULT_API_URL
    api_key: str | None = None
    project_id: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def upload_enabled(self) -> bool:
        """Whether a finished trace has anywhere to go.

        Runs live under a project, so without a project id there is no address
        to upload to. The SDK then stays purely in-memory and never opens a
        socket -- which is also what keeps it usable in tests and offline.
        """
        return bool(self.project_id)

    @classmethod
    def from_env(cls) -> TracerConfig:
        """Build configuration from environment variables."""
        return cls(
            api_url=os.environ.get(ENV_API_URL, DEFAULT_API_URL).rstrip("/"),
            api_key=os.environ.get(ENV_API_KEY) or None,
            project_id=os.environ.get(ENV_PROJECT_ID) or None,
            timeout_seconds=_timeout_from_env(os.environ.get(ENV_TIMEOUT)),
        )

    def __repr__(self) -> str:
        """Redact the key so configuration is safe to log."""
        key = "***" if self.api_key else None
        return (
            f"TracerConfig(api_url={self.api_url!r}, api_key={key!r}, "
            f"project_id={self.project_id!r}, "
            f"timeout_seconds={self.timeout_seconds!r})"
        )
