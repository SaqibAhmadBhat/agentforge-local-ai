"""Tool registry: the only actions the agent is allowed to take.

Each tool is a deterministic Python function with an explicit parameter list.
The registry:

1. publishes a JSON schema for each tool, so the model knows what it can call;
2. validates every call (tool name, argument names, types and lengths) BEFORE running it;
3. runs the tool and always returns text, even on failure, so the agent loop
   can show the error to the model instead of crashing;
4. truncates long results so the conversation stays a bounded size.

There is deliberately no tool that runs Python code or shell commands.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agentforge.calculator import MAX_EXPRESSION_LENGTH, calculate
from agentforge.errors import ToolError, ToolValidationError
from agentforge.notes import MAX_NAME_LENGTH, MAX_NOTE_CHARS, MAX_QUERY_LENGTH, NoteStore

logger = logging.getLogger(__name__)

_JSON_TYPES = {str: "string", int: "integer"}


@dataclass(frozen=True)
class Parameter:
    """One argument of a tool."""

    name: str
    type: type  # str or int
    description: str
    max_length: int = 1000  # for strings
    required: bool = True


@dataclass(frozen=True)
class Tool:
    """A named, documented, validated action the agent may take."""

    name: str
    description: str
    function: Callable[..., str]
    parameters: tuple[Parameter, ...] = ()

    def schema(self) -> dict[str, Any]:
        """The JSON schema sent to the model (Ollama's 'function' tool format)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: {"type": _JSON_TYPES[p.type], "description": p.description} for p in self.parameters
                    },
                    "required": [p.name for p in self.parameters if p.required],
                },
            },
        }


@dataclass(frozen=True)
class ToolResult:
    """Outcome of one tool call. `output` is always text the model can read."""

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    output: str = ""


class ToolRegistry:
    """Holds the allowed tools and validates/executes calls to them."""

    def __init__(self, tools: Iterable[Tool], max_result_chars: int = 2000) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool
        self.max_result_chars = max_result_chars

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    @property
    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def validate(self, name: Any, raw_arguments: Any) -> tuple[Tool, dict[str, Any]]:
        """Check a requested call and return the tool plus clean arguments.

        Raises:
            ToolValidationError: unknown tool, malformed arguments, unexpected or
                missing arguments, wrong types or over-long values.
        """
        if not isinstance(name, str) or name not in self._tools:
            raise ToolValidationError(f"Unknown tool '{name}'. Allowed tools: {', '.join(self._tools)}.")
        tool = self._tools[name]
        arguments = _decode_arguments(raw_arguments)

        allowed = {p.name for p in tool.parameters}
        unexpected = sorted(set(arguments) - allowed)
        if unexpected:
            expected = ", ".join(sorted(allowed)) or "no arguments"
            raise ToolValidationError(
                f"Tool '{name}' got unexpected argument(s): {', '.join(unexpected)}. It takes: {expected}."
            )

        clean: dict[str, Any] = {}
        for param in tool.parameters:
            if param.name not in arguments:
                if param.required:
                    raise ToolValidationError(f"Tool '{name}' is missing required argument '{param.name}'.")
                continue
            value = arguments[param.name]
            # bool is a subclass of int, so it is rejected explicitly.
            if not isinstance(value, param.type) or isinstance(value, bool):
                raise ToolValidationError(
                    f"Argument '{param.name}' of tool '{name}' must be {_JSON_TYPES[param.type]}, "
                    f"not {type(value).__name__}."
                )
            if isinstance(value, str) and len(value) > param.max_length:
                raise ToolValidationError(
                    f"Argument '{param.name}' of tool '{name}' is too long (maximum {param.max_length} characters)."
                )
            clean[param.name] = value
        return tool, clean

    def execute(self, name: Any, raw_arguments: Any = None) -> ToolResult:
        """Validate and run a tool. Never raises: failures come back as ok=False results."""
        tool_name = name if isinstance(name, str) else repr(name)
        try:
            tool, arguments = self.validate(name, raw_arguments)
        except ToolValidationError as exc:
            return ToolResult(tool_name, {}, ok=False, output=str(exc))

        try:
            output = tool.function(**arguments)
        except ToolError as exc:  # expected failures, e.g. division by zero or missing note
            return ToolResult(tool_name, arguments, ok=False, output=str(exc))
        except Exception as exc:  # noqa: BLE001 - a buggy tool must not crash the agent
            # Only the exception type is logged: arguments may contain private note text.
            logger.error("Tool %s raised %s", tool_name, type(exc).__name__)
            return ToolResult(tool_name, arguments, ok=False, output=f"Internal error in tool '{tool_name}'.")

        if not isinstance(output, str):
            logger.error("Tool %s returned %s instead of str", tool_name, type(output).__name__)
            return ToolResult(tool_name, arguments, ok=False, output=f"Internal error in tool '{tool_name}'.")
        return ToolResult(tool_name, arguments, ok=True, output=truncate(output, self.max_result_chars))


def truncate(text: str, limit: int) -> str:
    """Shorten text to `limit` characters, saying how much was cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} characters]"


def _decode_arguments(raw: Any) -> dict[str, Any]:
    """Accept a dict, a JSON object string, or nothing; reject anything else."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise ToolValidationError("Tool arguments must be a JSON object.") from None
    if not isinstance(raw, dict):
        raise ToolValidationError("Tool arguments must be a JSON object.")
    if not all(isinstance(key, str) for key in raw):
        raise ToolValidationError("Tool argument names must be text.")
    return dict(raw)


# --- The default tool set -----------------------------------------------------------

CLI_COMMANDS_HELP = """Commands you can type in the AgentForge terminal:
  /help              show this help
  /tools             list the tools the agent can use
  /run TOOL [ARGS]   run a tool directly, without the model
                     e.g. /run calculator 15 * 4   or   /run read_note {"name": "groceries"}
  /notes             list saved notes
  /status            show settings and check the Ollama connection
  /reset             forget the current conversation
  /trace             show or hide the agent's tool steps
  /quit              exit"""


def build_default_registry(
    note_store: NoteStore,
    max_result_chars: int = 2000,
    clock: Callable[[], datetime] | None = None,
) -> ToolRegistry:
    """Create the registry with AgentForge's built-in tools.

    Args:
        note_store: where notes are kept.
        max_result_chars: tool output longer than this is truncated.
        clock: returns the current time; injectable so tests are deterministic.
    """
    now = clock or (lambda: datetime.now().astimezone())

    def calculator(expression: str) -> str:
        return calculate(expression)

    def save_note(name: str, content: str) -> str:
        return note_store.save(name, content)

    def read_note(name: str) -> str:
        return note_store.read(name)

    def list_notes() -> str:
        names = note_store.list_names()
        return ", ".join(names) if names else "No notes saved yet."

    def search_notes(query: str) -> str:
        hits = note_store.search(query)
        if not hits:
            return f"No notes contain '{query.strip()}'."
        return "\n".join(f"- {hit.name}: {hit.snippet}" for hit in hits)

    def current_datetime() -> str:
        moment = now()
        return moment.strftime("%A, %d %B %Y, %H:%M:%S") + (f" ({moment.tzname()})" if moment.tzname() else "")

    def word_count(text: str) -> str:
        return f"{len(text.split())} words, {len(text)} characters"

    def get_help() -> str:
        lines = ["Tools AgentForge can use:"]
        lines += [f"  {tool.name}: {tool.description}" for tool in tools]
        return "\n".join(lines) + "\n\n" + CLI_COMMANDS_HELP

    tools = [
        Tool(
            "calculator",
            "Evaluate an arithmetic expression exactly. Use this for ANY arithmetic instead of mental math. "
            "Supports numbers, + - * / // % ** and parentheses, e.g. '0.15 * 1240'.",
            calculator,
            (Parameter("expression", str, "Arithmetic expression, e.g. '(12 + 8) * 3'", MAX_EXPRESSION_LENGTH),),
        ),
        Tool(
            "save_note",
            "Save a new local note. Fails if a note with that name already exists.",
            save_note,
            (
                Parameter("name", str, "Short note name, e.g. 'groceries'", MAX_NAME_LENGTH),
                Parameter("content", str, "The text to store", MAX_NOTE_CHARS),
            ),
        ),
        Tool(
            "read_note",
            "Read the full text of a saved note by name.",
            read_note,
            (Parameter("name", str, "Name of the note to read", MAX_NAME_LENGTH),),
        ),
        Tool("list_notes", "List the names of all saved notes.", list_notes),
        Tool(
            "search_notes",
            "Find notes whose name or text contains the given words (case-insensitive).",
            search_notes,
            (Parameter("query", str, "Text to look for", MAX_QUERY_LENGTH),),
        ),
        Tool("current_datetime", "Get the current local date, day of the week and time.", current_datetime),
        Tool(
            "word_count",
            "Count the words and characters in a piece of text.",
            word_count,
            (Parameter("text", str, "The text to measure", MAX_NOTE_CHARS),),
        ),
        Tool("get_help", "Explain what AgentForge can do and which commands are available.", get_help),
    ]
    return ToolRegistry(tools, max_result_chars=max_result_chars)
