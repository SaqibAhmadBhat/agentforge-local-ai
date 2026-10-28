"""Offline and no-cloud-fallback behaviour.

These tests check what the code actually does on the network:
- a complete agent run only ever opens connections to 127.0.0.1;
- HTTP proxy settings are ignored for model traffic;
- when the local model service is down the error is raised - nothing else is tried;
- no cloud LLM SDK is a dependency, and the source never contacts remote hosts.
"""

import ast
import re
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from helpers import free_port

from agentforge.agent import Agent
from agentforge.config import is_loopback_url
from agentforge.errors import LLMUnavailableError
from agentforge.llm import OllamaBackend
from agentforge.notes import NoteStore
from agentforge.tools import build_default_registry

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "agentforge"
PYPROJECT = PACKAGE_DIR.parent / "pyproject.toml"


@pytest.fixture
def connection_log(monkeypatch):
    """Record every outgoing TCP connection and block any that leave this computer."""
    attempts: list[str] = []
    real_connect = socket.socket.connect

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else str(address)
        attempts.append(host)
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError(f"Attempted non-local connection to {host}")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return attempts


def test_agent_run_only_connects_to_loopback(settings, ollama_stub, connection_log):
    ollama_stub.queue_chat(tool_calls=[("save_note", {"name": "secret", "content": "private text"})])
    ollama_stub.queue_chat(content="Saved.")
    settings = replace(settings, ollama_url=ollama_stub.url)
    backend = OllamaBackend(settings)
    agent = Agent(backend, build_default_registry(NoteStore(settings.notes_dir)), settings)

    assert backend.check().ok
    assert agent.run("save a note").answer == "Saved."
    assert connection_log and set(connection_log) == {"127.0.0.1"}
    assert (settings.notes_dir / "secret.txt").read_text() == "private text"


def test_proxy_environment_variables_are_ignored(settings, ollama_stub, monkeypatch):
    # If the HTTP client honoured these, every request would fail (nothing listens there).
    dead_proxy = f"http://127.0.0.1:{free_port()}"
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(key, dead_proxy)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    ollama_stub.queue_chat(content="hello")
    backend = OllamaBackend(replace(settings, ollama_url=ollama_stub.url))
    assert backend.chat([{"role": "user", "content": "hi"}], []).content == "hello"
    assert backend.check().reachable


def test_no_fallback_when_local_service_is_down(settings, connection_log):
    settings = replace(settings, ollama_url=f"http://127.0.0.1:{free_port()}")
    agent = Agent(OllamaBackend(settings), build_default_registry(NoteStore(settings.notes_dir)), settings)
    with pytest.raises(LLMUnavailableError):
        agent.run("hello")
    assert set(connection_log) == {"127.0.0.1"}  # it tried the local server and nothing else


def test_no_cloud_llm_sdk_in_dependencies():
    text = PYPROJECT.read_text().lower()
    for sdk in (
        "openai",
        "anthropic",
        "google-generativeai",
        "google-genai",
        "cohere",
        "groq",
        "mistralai",
        "langchain",
        "litellm",
    ):
        assert sdk not in text


def test_source_contains_no_remote_endpoints():
    """The only non-loopback URL in the package (Python, HTML, JS) is the Ollama download link shown to users.

    This also means the web interface loads no external fonts, scripts or images.
    URL templates such as f"http://{host}" are skipped here; what is actually contacted
    at run time is checked by the socket-level guard above.
    """
    files = [*PACKAGE_DIR.glob("*.py"), *PACKAGE_DIR.glob("static/*.html"), *PACKAGE_DIR.glob("static/*.js")]
    assert len(files) > 5
    for path in files:
        for url in re.findall(r"https?://[^\s\"'`)<>]+", path.read_text()):
            url = url.rstrip(".,")
            if "{" in url:
                continue
            assert is_loopback_url(url) or url == "https://ollama.com/download", f"{path.name} mentions {url}"


def test_source_never_executes_generated_code():
    """Scan the package's syntax trees for code-execution calls and risky imports."""
    forbidden_builtins = {"eval", "exec", "compile", "__import__"}
    forbidden_modules = {"subprocess", "pickle", "shelve", "marshal", "ctypes"}
    for path in PACKAGE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_builtins, f"{path.name} calls {node.func.id}()"
            func = node.func if isinstance(node, ast.Call) else None
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "os":
                attr = func.attr  # os.system, os.popen, os.exec*, os.spawn*
                assert attr not in {"system", "popen"} and not attr.startswith(("exec", "spawn")), (
                    f"{path.name} calls os.{attr}()"
                )
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert forbidden_modules.isdisjoint(m.split(".")[0] for m in modules), f"{path.name} imports {modules}"
