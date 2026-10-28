"""Unit tests for the agent loop, using a scripted fake model (no Ollama needed)."""

from dataclasses import replace

import pytest
from helpers import FakeBackend, reply

from agentforge.agent import (
    STOP_FINAL_ANSWER,
    STOP_ITERATION_LIMIT,
    STOP_REPEATED_CALLS,
    SYSTEM_PROMPT,
    Agent,
)
from agentforge.errors import InputError, LLMUnavailableError
from agentforge.notes import NoteStore
from agentforge.tools import build_default_registry


def make_agent(settings, backend, **overrides):
    settings = replace(settings, **overrides)
    registry = build_default_registry(NoteStore(settings.notes_dir), settings.max_tool_result_chars)
    return Agent(backend, registry, settings)


def test_direct_answer_without_tools(settings):
    backend = FakeBackend(reply("Hello! How can I help?"))
    result = make_agent(settings, backend).run("hi")
    assert result.answer == "Hello! How can I help?"
    assert result.stop_reason == STOP_FINAL_ANSWER and result.iterations == 1 and result.steps == []
    sent = backend.requests[0]
    assert sent[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert sent[-1] == {"role": "user", "content": "hi"}


def test_tool_call_then_final_answer(settings):
    backend = FakeBackend(
        reply("", ("calculator", {"expression": "0.15 * 1240"})),
        reply("15% of 1240 is 186."),
    )
    result = make_agent(settings, backend).run("What is 15% of 1240?")
    assert result.answer == "15% of 1240 is 186."
    assert result.iterations == 2
    assert [(s.tool, s.ok, s.output) for s in result.steps] == [("calculator", True, "186")]
    # The tool result is sent back to the model on the second request.
    second = backend.requests[1]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["function"]["name"] == "calculator"
    assert second[-1] == {"role": "tool", "content": "186", "tool_name": "calculator"}


def test_multi_step_calculate_and_save_note(settings):
    backend = FakeBackend(
        reply("", ("calculator", {"expression": "12 * 7"})),
        reply("", ("save_note", {"name": "result", "content": "84"})),
        reply("Saved 84 to the note 'result'."),
    )
    result = make_agent(settings, backend).run("multiply 12 by 7 and save it as 'result'")
    assert result.stop_reason == STOP_FINAL_ANSWER
    assert (settings.notes_dir / "result.txt").read_text() == "84"


def test_unknown_tool_from_model_is_rejected_and_reported_back(settings):
    backend = FakeBackend(
        reply("", ("run_shell", {"command": "rm -rf /"})),
        reply("I can't run shell commands."),
    )
    result = make_agent(settings, backend).run("delete everything")
    step = result.steps[0]
    assert not step.ok and "Unknown tool 'run_shell'" in step.output
    assert backend.requests[1][-1]["content"].startswith("Error: Unknown tool 'run_shell'")
    assert result.answer == "I can't run shell commands."


def test_invalid_arguments_from_model_are_rejected(settings):
    backend = FakeBackend(
        reply("", ("calculator", {"expr": "2+2"})),
        reply("", ("calculator", {"expression": "2+2"})),
        reply("4"),
    )
    result = make_agent(settings, backend).run("2+2?")
    assert [s.ok for s in result.steps] == [False, True]
    assert "unexpected argument" in result.steps[0].output


@pytest.mark.parametrize("bad_arguments", ["{not json", 12345, ["a"], None])
def test_malformed_tool_arguments_do_not_crash(settings, bad_arguments):
    backend = FakeBackend(reply("", ("calculator", bad_arguments)), reply("Sorry."))
    result = make_agent(settings, backend).run("calc")
    assert result.stop_reason == STOP_FINAL_ANSWER
    assert not result.steps[0].ok


def test_iteration_limit_stops_the_loop(settings):
    # A model that never stops calling tools (with different arguments each time).
    script = [reply("", ("calculator", {"expression": f"{i} + 1"})) for i in range(10)]
    backend = FakeBackend(*script)
    result = make_agent(settings, backend, max_iterations=3).run("loop forever")
    assert result.stop_reason == STOP_ITERATION_LIMIT
    assert result.iterations == 3 and len(backend.requests) == 3
    assert "stopped after 3 steps" in result.answer
    assert "Last successful tool result (calculator): 3" in result.answer


def test_repeated_identical_calls_are_not_re_executed_and_stop_the_loop(settings):
    call = ("save_note", {"name": "dup", "content": "x"})
    backend = FakeBackend(reply("", call), reply("", call), reply("", call), reply("never reached"))
    result = make_agent(settings, backend).run("save")
    assert result.stop_reason == STOP_REPEATED_CALLS
    assert [s.repeated for s in result.steps] == [False, True, True]
    assert "already called save_note" in result.steps[1].output
    assert len(backend.requests) == 3


def test_too_many_tool_calls_in_one_step_are_skipped(settings):
    calls = [("calculator", {"expression": f"{i}*2"}) for i in range(5)]
    backend = FakeBackend(reply("", *calls), reply("done"))
    result = make_agent(settings, backend, max_tool_calls_per_step=2).run("many")
    assert [s.skipped for s in result.steps] == [False, False, True, True, True]
    assert len(backend.requests[1]) == 2 + 1 + 5  # system, user, assistant, 5 tool messages


def test_empty_model_answer_is_explained(settings):
    result = make_agent(settings, FakeBackend(reply(""))).run("hi")
    assert "empty answer" in result.answer
    result = make_agent(settings, FakeBackend(reply("", done_reason="length"))).run("hi")
    assert "output limit" in result.answer


@pytest.mark.parametrize("text", ["", "   ", None])
def test_empty_input_is_rejected_before_the_model(settings, text):
    backend = FakeBackend()
    with pytest.raises(InputError):
        make_agent(settings, backend).run(text)
    assert backend.requests == []


def test_overlong_input_is_rejected_before_the_model(settings):
    backend = FakeBackend()
    with pytest.raises(InputError, match="limit is 100"):
        make_agent(settings, backend, max_input_chars=100).run("x" * 101)
    assert backend.requests == []


def test_model_service_failure_propagates_without_fallback(settings):
    backend = FakeBackend(LLMUnavailableError("Cannot connect to Ollama"))
    agent = make_agent(settings, backend)
    with pytest.raises(LLMUnavailableError):
        agent.run("hi")
    assert agent.history == []


def test_history_is_kept_and_trimmed(settings):
    backend = FakeBackend(reply("A1"), reply("A2"), reply("A3"))
    agent = make_agent(settings, backend, history_turns=2)
    for question in ["Q1", "Q2", "Q3"]:
        agent.run(question)
    assert [m["content"] for m in agent.history] == ["Q2", "A2", "Q3", "A3"]
    assert [m["content"] for m in backend.requests[2][1:]] == ["Q1", "A1", "Q2", "A2", "Q3"]
    agent.reset()
    assert agent.history == []


def test_history_can_be_disabled(settings):
    agent = make_agent(settings, FakeBackend(reply("A")), history_turns=0)
    agent.run("Q")
    assert agent.history == []


def test_on_step_callback_receives_each_step(settings):
    seen = []
    backend = FakeBackend(reply("", ("word_count", {"text": "a b c"})), reply("3 words"))
    agent = make_agent(settings, backend)
    agent.on_step = seen.append
    agent.run("count")
    assert [(s.tool, s.output) for s in seen] == [("word_count", "3 words, 5 characters")]
