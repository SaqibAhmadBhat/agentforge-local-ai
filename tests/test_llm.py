"""Tests for the Ollama backend.

Part 1 (unit): a fake `ollama.Client` raises specific exceptions, checking that each
becomes the right AgentForge error with a helpful hint.
Part 2 (integration): the real `ollama` package talks over HTTP to a stub server on
127.0.0.1 (helpers.OllamaStub), covering the request/response format, malformed
replies, error statuses and timeouts - still without a real model.
"""

from dataclasses import replace
from types import SimpleNamespace

import httpx
import ollama
import pytest
from helpers import free_port

from agentforge.agent import STOP_FINAL_ANSWER, Agent
from agentforge.errors import (
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelCapabilityError,
    ModelNotFoundError,
)
from agentforge.llm import OllamaBackend, parse_version, strip_thinking
from agentforge.notes import NoteStore
from agentforge.tools import build_default_registry


class RaisingClient:
    def __init__(self, exc):
        self.exc = exc

    def chat(self, **kwargs):
        raise self.exc

    def show(self, model):
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "error_type", "hint_text"),
    [
        (ConnectionError("Failed to connect to Ollama"), LLMUnavailableError, "ollama serve"),
        (httpx.ConnectError("refused"), LLMUnavailableError, "ollama serve"),
        (httpx.ReadTimeout("slow"), LLMTimeoutError, "AGENTFORGE_TIMEOUT_SECONDS"),
        (
            ollama.ResponseError('model "qwen3:4b" not found, try pulling it first', 404),
            ModelNotFoundError,
            "ollama pull qwen3:4b",
        ),
        (
            ollama.ResponseError("registry.ollama.ai/library/gemma:2b does not support tools", 400),
            ModelCapabilityError,
            "tool-capable",
        ),
        (
            ollama.ResponseError('"llama3.2:3b" does not support thinking', 400),
            ModelCapabilityError,
            "AGENTFORGE_THINK=false",
        ),
        (ollama.ResponseError("out of memory", 500), LLMResponseError, ""),
        (ValueError("Expecting value: line 1 column 1"), LLMResponseError, ""),
    ],
)
def test_errors_are_translated(settings, exc, error_type, hint_text):
    backend = OllamaBackend(settings, client=RaisingClient(exc))
    with pytest.raises(error_type) as caught:
        backend.chat([{"role": "user", "content": "hi"}], [])
    assert hint_text in caught.value.hint


def test_reply_parsing_handles_tool_calls_and_thinking_leaks():
    function = SimpleNamespace(name="calculator", arguments={"expression": "1+1"})
    message = SimpleNamespace(content="<think>let me add</think>  ", tool_calls=[SimpleNamespace(function=function)])
    parsed = OllamaBackend._parse_reply(SimpleNamespace(message=message, done_reason="stop"))
    assert parsed.content == ""
    assert parsed.tool_calls[0].name == "calculator" and parsed.tool_calls[0].arguments == {"expression": "1+1"}


def test_reply_without_message_is_malformed():
    with pytest.raises(LLMResponseError):
        OllamaBackend._parse_reply(SimpleNamespace(done_reason="stop"))


def test_helpers():
    assert strip_thinking("<think>\nhmm\n</think>\nAnswer") == "Answer"
    assert parse_version("0.12.3") == (0, 12, 3)
    assert parse_version("0.9.0-rc2") == (0, 9, 0)
    assert parse_version("1") == (1, 0, 0)


# --- Integration with the stub HTTP server -------------------------------------------------


def stub_settings(settings, stub, **overrides):
    return replace(settings, ollama_url=stub.url, **overrides)


def test_full_agent_run_over_http(settings, ollama_stub):
    ollama_stub.queue_chat(tool_calls=[("calculator", {"expression": "0.15 * 1240"})])
    ollama_stub.queue_chat(content="15% of 1240 is 186.")
    settings = stub_settings(settings, ollama_stub, num_gpu=0)
    backend = OllamaBackend(settings)
    agent = Agent(backend, build_default_registry(NoteStore(settings.notes_dir)), settings)

    result = agent.run("What is 15% of 1240?")

    assert result.stop_reason == STOP_FINAL_ANSWER and result.answer == "15% of 1240 is 186."
    first, second = ollama_stub.chat_requests
    assert first["model"] == "qwen3:4b" and first["think"] is True and first["stream"] is False
    assert first["options"]["num_gpu"] == 0 and first["options"]["num_predict"] == settings.max_output_tokens
    assert {t["function"]["name"] for t in first["tools"]} >= {"calculator", "save_note"}
    assert second["messages"][-1] == {"role": "tool", "content": "186", "tool_name": "calculator"}


def test_unreachable_server(settings):
    backend = OllamaBackend(replace(settings, ollama_url=f"http://127.0.0.1:{free_port()}"))
    with pytest.raises(LLMUnavailableError):
        backend.chat([{"role": "user", "content": "hi"}], [])
    status = backend.check(timeout=2)
    assert not status.ok and not status.reachable
    assert "Cannot connect to Ollama" in status.problems[0]


def test_missing_model_over_http(settings, ollama_stub):
    ollama_stub.chat_responses.append((404, {"error": 'model "tiny:1b" not found, try pulling it first'}))
    backend = OllamaBackend(stub_settings(settings, ollama_stub, model="tiny:1b"))
    with pytest.raises(ModelNotFoundError, match="tiny:1b"):
        backend.chat([{"role": "user", "content": "hi"}], [])
    status = backend.check()
    assert status.reachable and not status.model_available
    assert "ollama pull tiny:1b" in status.problems[0]


@pytest.mark.parametrize(
    "body",
    [
        "this is not json",
        '{"model": "x", "message": {"role": "assistant", "content": "", '
        '"tool_calls": [{"function": {"name": "calculator", "arguments": "not-a-dict"}}]}}',
    ],
)
def test_malformed_response_over_http(settings, ollama_stub, body):
    ollama_stub.chat_responses.append((200, body))
    backend = OllamaBackend(stub_settings(settings, ollama_stub))
    with pytest.raises(LLMResponseError, match="malformed"):
        backend.chat([{"role": "user", "content": "hi"}], [])


def test_server_error_status_over_http(settings, ollama_stub):
    ollama_stub.chat_responses.append((500, {"error": "llama runner process has terminated"}))
    backend = OllamaBackend(stub_settings(settings, ollama_stub))
    with pytest.raises(LLMResponseError, match="HTTP 500"):
        backend.chat([{"role": "user", "content": "hi"}], [])


def test_timeout_over_http(settings, ollama_stub):
    ollama_stub.delay_seconds = 2
    ollama_stub.queue_chat(content="too late")
    backend = OllamaBackend(stub_settings(settings, ollama_stub, request_timeout=1))
    with pytest.raises(LLMTimeoutError):
        backend.chat([{"role": "user", "content": "hi"}], [])


def test_health_check_ok(settings, ollama_stub):
    status = OllamaBackend(stub_settings(settings, ollama_stub)).check()
    assert status.ok and status.server_version == "0.12.0"
    assert status.capabilities == ["completion", "tools", "thinking"]


def test_health_check_reports_old_server_and_missing_capabilities(settings, ollama_stub):
    ollama_stub.version = "0.5.1"
    ollama_stub.models["gemma:2b"] = ["completion"]
    status = OllamaBackend(stub_settings(settings, ollama_stub, model="gemma:2b")).check()
    assert not status.ok
    joined = " ".join(status.problems)
    assert "older than 0.9.0" in joined and "tool calling" in joined and "AGENTFORGE_THINK=false" in joined


def test_list_models_excludes_cloud_models(settings, ollama_stub):
    ollama_stub.models["gpt-oss:120b-cloud"] = ["completion", "tools"]
    ollama_stub.models["llama3.2:3b"] = ["completion", "tools"]
    backend = OllamaBackend(stub_settings(settings, ollama_stub))
    assert backend.list_models() == ["llama3.2:3b", "qwen3:4b"]


def test_list_models_when_unreachable(settings):
    backend = OllamaBackend(replace(settings, ollama_url=f"http://127.0.0.1:{free_port()}"))
    with pytest.raises(LLMUnavailableError):
        backend.list_models()
