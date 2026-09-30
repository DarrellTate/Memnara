"""Agent-loop errors. Diagnosable; not swallowed into fake successful steps."""


class AgentError(Exception):
    """Base agent/autonomy error."""


class ReasoningError(AgentError):
    """Reasoning provider failed."""


class ReasoningTimeoutError(ReasoningError):
    """Reasoning HTTP call exceeded the configured timeout."""


class MalformedProposalError(AgentError):
    """Model output was not a valid single action proposal."""


class InvalidActionError(AgentError):
    """Action name, parameters, or runtime support was rejected."""


class OwnershipDeniedError(AgentError):
    """Gameplay input was refused because the owner is not AI_CONTROL."""


class ExecutionFailedError(AgentError):
    """Validated action could not be applied through the executor."""


class StuckTerminatedError(AgentError):
    """Stuck recovery exhausted; user intervention is required."""


class PerceptionFailedError(AgentError):
    """A required observation could not be produced."""
