"""OPTIONAL live tests against a real Ollama server and model.

Skipped unless AGENTFORGE_LIVE_TESTS=1. They need Ollama running and the model
pulled (default qwen3:4b). Small models are not deterministic, so these check
behaviour (was the right tool called?) rather than exact wording, and a failure
can mean the model made a poor choice rather than a code bug.

    AGENTFORGE_LIVE_TESTS=1 .venv/bin/python -m pytest -m live -v
"""

import os
from dataclasses import replace

import pytest

from agentforge.agent import STOP_FINAL_ANSWER, Agent
from agentforge.config import load_settings
from agentforge.llm import OllamaBackend
from agentforge.notes import NoteStore
from agentforge.tools import build_default_registry

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("AGENTFORGE_LIVE_TESTS") != "1", reason="set AGENTFORGE_LIVE_TESTS=1 to run"),
]


@pytest.fixture
def live_agent(tmp_path, monkeypatch):
    # Re-read the developer's real environment and .env (the autouse fixture isolated them).
    monkeypatch.delenv("AGENTFORGE_ENV_FILE", raising=False)
    settings = replace(load_settings(), data_dir=tmp_path / "data")
    backend = OllamaBackend(settings)
    status = backend.check()
    if not status.ok:
        pytest.fail("Ollama is not ready: " + "; ".join(status.problems))
    return Agent(backend, build_default_registry(NoteStore(settings.notes_dir)), settings)


def test_live_calculator(live_agent):
    result = live_agent.run("What is 15% of 1240? Use the calculator.")
    assert result.stop_reason == STOP_FINAL_ANSWER
    assert any(step.tool == "calculator" and step.ok for step in result.steps)
    assert "186" in result.answer


def test_live_note_round_trip(live_agent):
    live_agent.run("Save a note named 'viva' with the text: explain the agent loop.")
    assert "viva" in live_agent.registry.execute("list_notes").output
    result = live_agent.run("Read my note named 'viva' and tell me what it says.")
    assert any(step.tool == "read_note" and step.ok for step in result.steps)


def test_live_no_tool_needed(live_agent):
    result = live_agent.run("In one sentence, what is a small language model?")
    assert result.stop_reason == STOP_FINAL_ANSWER and result.answer
    assert result.steps == []
