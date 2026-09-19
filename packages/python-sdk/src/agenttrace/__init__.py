"""AgentTrace Python SDK.

Records AI-agent executions — tool calls and their responses — so they can be
replayed against a future version of the agent. A run is buffered in memory and
uploaded to the AgentTrace API in one request when it ends; replay arrives in a
later milestone.

Recording is not allowed to change how the instrumented application behaves.
Tool results and exceptions pass through untouched, and any failure to record
or upload is logged to the ``agenttrace`` logger and swallowed.
"""

from agenttrace.config import TracerConfig
from agenttrace.models import RecordedEvent, ToolCall, Trace
from agenttrace.tracer import AgentTracer

__version__ = "0.1.0"

__all__ = [
    "AgentTracer",
    "RecordedEvent",
    "ToolCall",
    "Trace",
    "TracerConfig",
    "__version__",
]
