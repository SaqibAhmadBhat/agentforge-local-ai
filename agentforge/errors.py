"""Exception types used across AgentForge.

Every error a user can realistically hit has its own class, so the CLI can
print a specific, helpful message instead of a raw traceback.
"""


class AgentForgeError(Exception):
    """Base class for all AgentForge errors.

    `hint` is an optional, user-facing suggestion for fixing the problem.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


class ConfigError(AgentForgeError):
    """A setting in the environment or .env file is missing or invalid."""


class InputError(AgentForgeError):
    """The user's request was rejected before reaching the model (e.g. too long)."""


# --- Language-model service errors -------------------------------------------------


class LLMError(AgentForgeError):
    """Base class for problems talking to the local model service."""


class LLMUnavailableError(LLMError):
    """The Ollama server could not be reached (not installed, not running, wrong URL)."""


class LLMTimeoutError(LLMError):
    """The model did not answer within the configured timeout."""


class ModelNotFoundError(LLMError):
    """The configured model has not been downloaded into Ollama."""


class ModelCapabilityError(LLMError):
    """The model cannot do something AgentForge needs (tool calling or thinking)."""


class LLMResponseError(LLMError):
    """The server answered, but with an error status or a malformed response."""


# --- Tool errors --------------------------------------------------------------------


class ToolError(AgentForgeError):
    """Base class for tool problems. Converted into text the model can read."""


class ToolValidationError(ToolError):
    """The tool name or its arguments were rejected before execution."""


class ToolExecutionError(ToolError):
    """A valid tool call failed in an expected way (e.g. division by zero, missing note)."""
