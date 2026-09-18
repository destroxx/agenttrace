"""SDK configuration.

Values are read from the environment so that host applications never need to
hardcode an endpoint or a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_API_URL = "http://localhost:8000"

ENV_API_URL = "AGENTTRACE_API_URL"
ENV_API_KEY = "AGENTTRACE_API_KEY"


@dataclass(frozen=True, slots=True)
class TracerConfig:
    """Connection settings for the AgentTrace backend."""

    api_url: str = DEFAULT_API_URL
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> TracerConfig:
        """Build configuration from environment variables."""
        return cls(
            api_url=os.environ.get(ENV_API_URL, DEFAULT_API_URL).rstrip("/"),
            api_key=os.environ.get(ENV_API_KEY) or None,
        )

    def __repr__(self) -> str:
        """Redact the key so configuration is safe to log."""
        key = "***" if self.api_key else None
        return f"TracerConfig(api_url={self.api_url!r}, api_key={key!r})"
