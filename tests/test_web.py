"""Tests for the local web interface's HTTP API and its security checks.

The server runs in a background thread on 127.0.0.1 with a scripted fake model,
so no Ollama server or model is needed.
"""

import http.client
import io
import json
import socket
import threading

import pytest
from helpers import FakeBackend, reply

from agentforge.cli import main
from agentforge.errors import LLMUnavailableError
from agentforge.llm import ServiceStatus
from agentforge.web import MAX_BODY_BYTES, WebApp, create_server


class FakeRuntime(FakeBackend):
    """Fake model that also answers health checks and lists local models."""

    def check(self, timeout: float = 5.0) -> ServiceStatus:
        return ServiceStatus(
            url="http://127.0.0.1:11434",
            reachable=True,
            server_version="0.12.0",
            model_available=True,
            capabilities=["completion", "tools", "thinking"],
        )

    def list_models(self) -> list[str]:
        return ["llama3.2:3b", "qwen3:4b"]


@pytest.fixture
def web(settings):
    """Start a server; yields (app, request_function)."""
    backend = FakeRuntime()
    app = WebApp(settings, backend_factory=lambda s: backend)
    server = create_server(app, 0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(method, path, body=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        all_headers = {"Host": f"127.0.0.1:{port}"}
        if body is not None:
            all_headers["Content-Type"] = "application/json"
        all_headers.update(headers or {})
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection.request(method, path, body=payload, headers=all_headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        content_type = response.getheader("Content-Type", "")
        parsed = json.loads(data) if content_type.startswith("application/json") else data.decode()
        return response.status, parsed, response

    yield app, backend, request, port
    server.shutdown()
    server.server_close()


def test_page_and_static_files_are_served_with_security_headers(web):
    _, _, request, _ = web
    status, page, response = request("GET", "/")
    assert status == 200 and "<title>AgentForge Local AI</title>" in page
    assert "script-src 'self'" in response.getheader("Content-Security-Policy")
    assert response.getheader("X-Content-Type-Options") == "nosniff"
    assert response.getheader("X-Frame-Options") == "DENY"
    assert response.getheader("Access-Control-Allow-Origin") is None  # no CORS, ever
    for name in ("app.js", "app.css", "logo.svg"):
        assert request("GET", f"/static/{name}")[0] == 200


@pytest.mark.parametrize(
    "path", ["/static/../config.py", "/static/web.py", "/static/%2e%2e/web.py", "/nope", "/api/nope"]
)
def test_unknown_paths_and_traversal_are_refused(web, path):
    _, _, request, _ = web
    assert request("GET", path)[0] == 404


@pytest.mark.parametrize("host", ["evil.example.com", "192.168.1.5:8765", "127.0.0.1:1"])
def test_foreign_host_header_is_refused(web, host):
    _, _, request, _ = web
    assert request("GET", "/api/status", headers={"Host": host})[0] == 403
    assert request("POST", "/api/chat", body={"message": "hi"}, headers={"Host": host})[0] == 403


def test_cross_site_post_is_refused(web):
    _, backend, request, _ = web
    status, data, _ = request(
        "POST", "/api/chat", body={"message": "hi"}, headers={"Origin": "https://evil.example.com"}
    )
    assert status == 403 and "Cross-site" in data["error"]
    assert backend.requests == []  # the model was never called


def test_same_origin_post_is_accepted(web):
    _, backend, request, port = web
    backend.script.append(reply("Hello!"))
    status, data, _ = request(
        "POST", "/api/chat", body={"message": "hi"}, headers={"Origin": f"http://localhost:{port}"}
    )
    assert status == 200 and data["answer"] == "Hello!"


def test_post_must_be_json_and_small(web):
    _, _, request, _ = web
    assert (
        request("POST", "/api/chat", raw=b"message=hi", headers={"Content-Type": "application/x-www-form-urlencoded"})[
            0
        ]
        == 415
    )
    assert request("POST", "/api/chat", raw=b"{not json", headers={"Content-Type": "application/json"})[0] == 400
    assert request("POST", "/api/chat", raw=b"[1, 2]", headers={"Content-Type": "application/json"})[0] == 400
    big = json.dumps({"message": "x" * (MAX_BODY_BYTES + 1)}).encode()
    assert request("POST", "/api/chat", raw=big, headers={"Content-Type": "application/json"})[0] == 413


def test_chat_returns_answer_and_tool_steps(web):
    _, backend, request, _ = web
    backend.script += [reply("", ("calculator", {"expression": "0.15 * 1240"})), reply("It is 186.")]
    status, data, _ = request("POST", "/api/chat", body={"message": "15% of 1240?"})
    assert status == 200
    assert data["answer"] == "It is 186." and data["stop_reason"] == "final_answer" and data["iterations"] == 2
    assert data["steps"][0]["tool"] == "calculator" and data["steps"][0]["output"] == "186"


def test_chat_input_errors(web):
    _, _, request, _ = web
    assert request("POST", "/api/chat", body={"message": 42})[0] == 400
    status, data, _ = request("POST", "/api/chat", body={"message": "   "})
    assert status == 400 and data["kind"] == "InputError"


def test_chat_when_model_service_is_down(web):
    _, backend, request, _ = web
    backend.script.append(
        LLMUnavailableError("Cannot connect to Ollama at http://127.0.0.1:11434.", hint="Start Ollama")
    )
    status, data, _ = request("POST", "/api/chat", body={"message": "hi"})
    assert status == 503
    assert data["kind"] == "LLMUnavailableError" and data["hint"] == "Start Ollama"


def test_chat_is_refused_while_busy(web):
    app, _, request, _ = web
    app.busy.acquire()
    try:
        assert request("POST", "/api/chat", body={"message": "hi"})[0] == 409
    finally:
        app.busy.release()


def test_direct_tool_endpoint_validates_like_the_agent(web):
    _, backend, request, _ = web
    status, data, _ = request("POST", "/api/tool", body={"tool": "shell", "arguments": {"command": "ls"}})
    assert status == 200 and not data["ok"] and "Unknown tool 'shell'" in data["output"]
    _, data, _ = request("POST", "/api/tool", body={"tool": "calculator", "arguments": {"expression": "2**10"}})
    assert data["ok"] and data["output"] == "1024"
    _, data, _ = request(
        "POST", "/api/tool", body={"tool": "save_note", "arguments": {"name": "web", "content": "from the UI"}}
    )
    assert data["ok"]
    assert request("GET", "/api/notes")[1] == {"ok": True, "notes": ["web"], "message": ""}
    assert backend.requests == []  # direct tools never involve the model


def test_status_tools_and_models(web):
    _, _, request, _ = web
    status, data, _ = request("GET", "/api/status")
    assert status == 200 and data["app"]["name"] == "AgentForge Local AI"
    assert data["runtime"]["ok"] is True and data["model"] == "qwen3:4b"
    names = [tool["name"] for tool in request("GET", "/api/tools")[1]["tools"]]
    assert "calculator" in names and "save_note" in names
    assert request("GET", "/api/models")[1] == {"models": ["llama3.2:3b", "qwen3:4b"], "current": "qwen3:4b"}


def test_model_selection(web):
    app, backend, request, _ = web
    backend.script.append(reply("first"))
    request("POST", "/api/chat", body={"message": "remember me"})
    assert app.agent.history
    status, data, _ = request("POST", "/api/model", body={"model": "llama3.2:3b"})
    assert status == 200 and app.settings.model == "llama3.2:3b" and app.agent.history == []
    assert request("POST", "/api/model", body={"model": "gpt-oss:120b-cloud"})[0] == 400  # cloud refused
    status, data, _ = request("POST", "/api/model", body={"model": "mistral:7b"})
    assert status == 400 and "not downloaded" in data["error"]


def test_reset_clears_conversation(web):
    app, backend, request, _ = web
    backend.script.append(reply("ok"))
    request("POST", "/api/chat", body={"message": "hello"})
    assert request("POST", "/api/reset", body={})[0] == 200
    assert app.agent.history == []


def test_server_only_listens_on_loopback(web):
    *_, port = web
    with socket.socket() as sock:
        assert sock.connect_ex(("127.0.0.1", port)) == 0
    # The listening socket is bound to 127.0.0.1, not 0.0.0.0.
    app = WebApp.__new__(WebApp)
    server = create_server(app, 0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


def test_web_flag_reports_port_in_use(monkeypatch):
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        out = io.StringIO()
        code = main(["--web", "--port", str(port)], out=out)
    assert code == 1 and "Could not start the web interface" in out.getvalue()
