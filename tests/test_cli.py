"""Tests for the terminal interface (run in-process with captured output)."""

import io

from helpers import free_port

from agentforge import __version__
from agentforge.cli import EXIT_OK, EXIT_SERVICE, EXIT_USAGE, AgentForgeCLI, main
from agentforge.config import load_settings


def run_cli(argv):
    out = io.StringIO()
    code = main(argv, out=out)
    return code, out.getvalue()


def test_check_reports_unavailable_service(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", f"http://127.0.0.1:{free_port()}")
    code, output = run_cli(["--check"])
    assert code == EXIT_SERVICE
    assert "Ollama reachable: no" in output and "ollama serve" in output


def test_check_with_working_service(monkeypatch, ollama_stub):
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", ollama_stub.url)
    code, output = run_cli(["--check"])
    assert code == EXIT_OK and "Ready" in output


def test_one_shot_question(monkeypatch, ollama_stub):
    ollama_stub.queue_chat(tool_calls=[("calculator", {"expression": "2+2"})])
    ollama_stub.queue_chat(content="2 + 2 = 4")
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", ollama_stub.url)
    code, output = run_cli(["what", "is", "2+2"])
    assert code == EXIT_OK
    assert "calculator" in output and "AgentForge: 2 + 2 = 4" in output


def test_one_shot_with_service_down_gives_helpful_error(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", f"http://127.0.0.1:{free_port()}")
    code, output = run_cli(["hello"])
    assert code == EXIT_SERVICE
    assert "Cannot connect to Ollama" in output and "Traceback" not in output


def test_configuration_error_exit_code(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", "http://203.0.113.9:11434")
    code, output = run_cli(["--check"])
    assert code == EXIT_USAGE and "Configuration error" in output


def test_model_override_is_validated():
    code, output = run_cli(["--model", "gpt-oss:120b-cloud", "--check"])
    assert code == EXIT_USAGE and "cloud model" in output


def test_version_flag(capsys):
    try:
        main(["--version"])
    except SystemExit as exit_:
        assert exit_.code == 0
    assert __version__ in capsys.readouterr().out


def test_repl_commands_work_without_a_model(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", f"http://127.0.0.1:{free_port()}")
    out = io.StringIO()
    app = AgentForgeCLI(load_settings(), out=out)
    lines = iter(
        [
            "/run calculator 15 * 4",
            '/run shell {"command": "ls"}',
            '/run calculator {"expression": "__import__(\'os\')"}',
            '/run save_note {"name": "demo", "content": "AgentForge demo note"}',
            "/notes",
            "/run read_note demo",
            "/run calculator 1/0",
            "/tools",
            "/help",
            "/bogus",
            "/quit",
        ]
    )
    assert app.repl(read_line=lambda prompt: next(lines)) == EXIT_OK
    text = out.getvalue()
    assert "Problem: Cannot connect to Ollama" in text
    assert "[calculator] 60" in text
    assert "Unknown tool 'shell'" in text
    assert "Only numbers" in text
    assert "[list_notes] demo" in text and "[read_note] AgentForge demo note" in text
    assert "Division by zero" in text
    assert "save_note(name, content)" in text and "/run TOOL" in text
    assert "Unknown command /bogus" in text and "Bye." in text


def test_repl_chat_and_reset(monkeypatch, ollama_stub):
    ollama_stub.queue_chat(content="Hi there!")
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", ollama_stub.url)
    out = io.StringIO()
    app = AgentForgeCLI(load_settings(), out=out)
    lines = iter(["hello", "/reset", "/trace", "exit"])
    app.repl(read_line=lambda prompt: next(lines))
    text = out.getvalue()
    assert "AgentForge: Hi there!" in text and "Conversation cleared." in text and "Tool trace off." in text
    assert app.agent.history == []


def test_repl_handles_ctrl_d(monkeypatch):
    monkeypatch.setenv("AGENTFORGE_OLLAMA_URL", f"http://127.0.0.1:{free_port()}")
    out = io.StringIO()

    def eof(prompt):
        raise EOFError

    assert AgentForgeCLI(load_settings(), out=out).repl(read_line=eof) == EXIT_OK


def test_application_starts_as_a_module():
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "agentforge", "--version"], capture_output=True, text=True, timeout=60
    )
    assert completed.returncode == 0 and "AgentForge Local AI 1.0.0" in completed.stdout
