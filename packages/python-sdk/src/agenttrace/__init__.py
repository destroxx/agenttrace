"""AgentTrace Python SDK.

Records AI-agent executions — tool calls and their responses — so they can be
replayed against a future version of the agent. This milestone provides the
in-process recording skeleton only; transport to the AgentTrace API and replay
arrive in later milestones.
"""

from agenttrace.config import TracerConfig
from agenttrace.models import ToolCall, Trace
from agenttrace.tracer import AgentTracer

__version__ = "0.1.0"

__all__ = ["AgentTracer", "ToolCall", "Trace", "TracerConfig", "__version__"]
