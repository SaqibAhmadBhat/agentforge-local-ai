"""The agent loop: decide -> (validate -> run tool -> observe)* -> final answer.

For each user request:

1. Send the conversation and the tool schemas to the local model.
2. If the model answers with text and no tool calls, that is the final answer.
3. Otherwise validate and run each requested tool through the ToolRegistry,
   append the results to the conversation, and ask the model again.
4. Stop when there is a final answer, when the iteration limit is reached,
   or when the model keeps repeating the same tool call.

The model only *proposes* actions; this Python code decides whether they run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentforge.config import Settings
from agentforge.errors import InputError
from agentforge.llm import ChatBackend, ToolCallRequest
from agentforge.tools import ToolRegistry, truncate

SYSTEM_PROMPT = """You are AgentForge, a helpful assistant that runs entirely on the user's own computer.

You can call these tools when they help:
- calculator: for ANY arithmetic. Never do arithmetic in your head.
- save_note, read_note, list_notes, search_notes: the user's local notes.
- current_datetime: today's date, the day of the week or the time.
- word_count: counting words or characters.
- get_help: when the user asks what you can do.

Rules:
- Answer greetings, general knowledge and conversation directly, without tools.
- Only use the tools listed above. Never invent a tool.
- Never claim you saved, read or calculated something unless a tool result confirms it.
- If a tool returns an error, explain it to the user or correct the arguments. Do not repeat an identical call.
- When you have what you need, give one short, clear final answer."""

# Stop if the model asks for the same (tool, arguments) pair this many times in one request.
MAX_REPEATED_CALLS = 2

STOP_FINAL_ANSWER = "final_answer"
STOP_ITERATION_LIMIT = "iteration_limit"
STOP_REPEATED_CALLS = "repeated_tool_calls"


@dataclass(frozen=True)
class AgentStep:
    """One tool call made while answering a request (shown in the CLI trace)."""

    iteration: int
    tool: str
    arguments: Any
    ok: bool
    output: str
    repeated: bool = False
    skipped: bool = False


@dataclass
class AgentResult:
    """Everything that happened while answering one request."""

    answer: str
    stop_reason: str
    iterations: int
    steps: list[AgentStep] = field(default_factory=list)


class Agent:
    """Runs the tool-using loop for one conversation."""

    def __init__(
        self,
        backend: ChatBackend,
        registry: ToolRegistry,
        settings: Settings,
        on_step: Callable[[AgentStep], None] | None = None,
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.settings = settings
        self.on_step = on_step
        self.history: list[dict[str, Any]] = []  # earlier user/assistant turns (no tool chatter)

    def reset(self) -> None:
        """Forget the conversation so far."""
        self.history.clear()

    def run(self, user_input: str) -> AgentResult:
        """Answer one user request, using tools as needed.

        Raises:
            InputError: if the request is empty or too long.
            LLMError: if the model service fails. There is deliberately no fallback.
        """
        text = (user_input or "").strip()
        if not text:
            raise InputError("Please type a request.")
        if len(text) > self.settings.max_input_chars:
            raise InputError(
                f"Your message is {len(text)} characters; the limit is {self.settings.max_input_chars}.",
                hint="Shorten it, or raise AGENTFORGE_MAX_INPUT_CHARS.",
            )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.history,
            {"role": "user", "content": text},
        ]
        tool_schemas = self.registry.schemas()
        steps: list[AgentStep] = []
        results_by_call: dict[str, str] = {}  # call key -> output, for repeat detection
        repeat_count = 0

        for iteration in range(1, self.settings.max_iterations + 1):
            reply = self.backend.chat(messages, tool_schemas)

            if not reply.tool_calls:
                answer = reply.content.strip() or self._empty_answer_message(reply.done_reason)
                self._remember(text, answer)
                return AgentResult(answer, STOP_FINAL_ANSWER, iteration, steps)

            allowed_calls = reply.tool_calls[: self.settings.max_tool_calls_per_step]
            skipped_calls = reply.tool_calls[self.settings.max_tool_calls_per_step :]
            messages.append(_assistant_message(reply.content, reply.tool_calls))

            for call in allowed_calls:
                key = _call_key(call)
                if key in results_by_call:
                    repeat_count += 1
                    output = (
                        f"You already called {call.name} with these arguments. "
                        f"The result was: {results_by_call[key]} Do not call it again; use this result."
                    )
                    step = AgentStep(iteration, call.name, call.arguments, False, output, repeated=True)
                else:
                    result = self.registry.execute(call.name, call.arguments)
                    output = result.output if result.ok else f"Error: {result.output}"
                    results_by_call[key] = output
                    step = AgentStep(iteration, call.name, call.arguments, result.ok, output)
                self._record(steps, step)
                messages.append({"role": "tool", "content": output, "tool_name": call.name})

            for call in skipped_calls:
                output = f"Skipped: at most {self.settings.max_tool_calls_per_step} tool calls are allowed per step."
                self._record(steps, AgentStep(iteration, call.name, call.arguments, False, output, skipped=True))
                messages.append({"role": "tool", "content": output, "tool_name": call.name})

            if repeat_count >= MAX_REPEATED_CALLS:
                answer = "I stopped because the model kept repeating the same tool call." + _last_result(steps)
                return AgentResult(answer, STOP_REPEATED_CALLS, iteration, steps)

        answer = (
            f"I stopped after {self.settings.max_iterations} steps without a final answer. "
            "Try a simpler or more specific request." + _last_result(steps)
        )
        return AgentResult(answer, STOP_ITERATION_LIMIT, self.settings.max_iterations, steps)

    # -- helpers ----------------------------------------------------------------------

    def _record(self, steps: list[AgentStep], step: AgentStep) -> None:
        steps.append(step)
        if self.on_step:
            self.on_step(step)

    def _remember(self, user_text: str, answer: str) -> None:
        """Keep the last few user/assistant turns so follow-up questions have context."""
        if self.settings.history_turns <= 0:
            return
        self.history += [
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": truncate(answer, self.settings.max_tool_result_chars)},
        ]
        self.history = self.history[-2 * self.settings.history_turns :]

    def _empty_answer_message(self, done_reason: str | None) -> str:
        if done_reason == "length":
            return (
                f"The model reached its output limit ({self.settings.max_output_tokens} tokens) before answering. "
                "Try AGENTFORGE_THINK=false or a higher AGENTFORGE_MAX_OUTPUT_TOKENS."
            )
        return "The model returned an empty answer. Please try rephrasing your request."


def _call_key(call: ToolCallRequest) -> str:
    """A stable text key for (tool name, arguments), used to detect repeated calls."""
    try:
        arguments = json.dumps(call.arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        arguments = repr(call.arguments)
    return f"{call.name}:{arguments}"


def _assistant_message(content: str, calls: list[ToolCallRequest]) -> dict[str, Any]:
    """Re-create the model's tool-call turn in the format Ollama expects in the history."""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {"function": {"name": call.name, "arguments": call.arguments if isinstance(call.arguments, dict) else {}}}
            for call in calls
        ],
    }


def _last_result(steps: list[AgentStep]) -> str:
    successful = [s for s in steps if s.ok and not s.repeated and not s.skipped]
    if not successful:
        return ""
    last = successful[-1]
    return f"\nLast successful tool result ({last.tool}): {last.output}"
