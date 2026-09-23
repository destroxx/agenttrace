"""AgentTrace Python SDK.

Records AI-agent executions — tool calls and their responses — and replays
them against a newer version of the agent. A run is buffered in memory and
uploaded to the AgentTrace API in one request when it ends. `tracer.replay`
runs the agent's own entry point again with every `@tracer.tool` answered
from a recording instead of executing.

Recording is not allowed to change how the instrumented application behaves.
Tool results and exceptions pass through untouched, and any failure to record
or upload is logged to the ``agenttrace`` logger and swallowed. Replay is test
tooling invoked on purpose, so it raises the exceptions in ``agenttrace.errors``
instead. `compare` (or `tracer.replay_and_compare`) turns a replay into a
deterministic PASS/FAIL report with the findings behind it.
"""

from agenttrace.comparison import ComparisonPolicy, ComparisonReport, Finding, compare
from agenttrace.config import TracerConfig
from agenttrace.errors import (
    AgentTraceAPIError,
    RecordingNotFound,
    ReplayedToolError,
    ReplayError,
    UnmatchedToolCall,
)
from agenttrace.models import RecordedEvent, ToolCall, Trace
from agenttrace.recording import RecordedToolCall, Recording
from agenttrace.replay import ReplayResult, ReplaySummary, ToolCallMatch, UnusedRecordedCall
from agenttrace.tracer import AgentTracer

__version__ = "0.1.0"

__all__ = [
    "AgentTraceAPIError",
    "AgentTracer",
    "ComparisonPolicy",
    "ComparisonReport",
    "Finding",
    "RecordedEvent",
    "RecordedToolCall",
    "Recording",
    "RecordingNotFound",
    "ReplayError",
    "ReplayResult",
    "ReplaySummary",
    "ReplayedToolError",
    "ToolCall",
    "ToolCallMatch",
    "Trace",
    "TracerConfig",
    "UnmatchedToolCall",
    "UnusedRecordedCall",
    "__version__",
    "compare",
]
