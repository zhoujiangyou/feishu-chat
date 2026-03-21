# AI GC START
class AgentRuntimeError(RuntimeError):
    """Base error for Agent runtime failures."""


class PlanningError(AgentRuntimeError):
    """Raised when the planner cannot produce a valid next action."""


class ToolExecutionError(AgentRuntimeError):
    """Raised when a tool call fails before producing a normalized observation."""


class VerificationError(AgentRuntimeError):
    """Raised when verification fails unexpectedly."""


class PolicyDeniedError(AgentRuntimeError):
    """Raised when the current policy blocks an action."""


class AgentSessionNotFoundError(AgentRuntimeError):
    """Raised when a requested session does not exist."""


class DoomLoopDetectedError(AgentRuntimeError):
    """Raised when the agent repeats the same tool call too many times."""
# AI GC END
