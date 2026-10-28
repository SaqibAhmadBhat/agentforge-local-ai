"""Test helpers: a scripted fake model backend and a stub Ollama HTTP server."""

from __future__ import annotations

import copy
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from agentforge.llm import ChatReply, ToolCallRequest

# --- Fake model backend ---------------------------------------------------------------


def reply(content: str = "", *calls: tuple[str, Any], done_reason: str = "stop") -> ChatReply:
    """Build a scripted model reply: reply("text") or reply("", ("calculator", {...}))."""
    return ChatReply(content, [ToolCallRequest(name, args) for name, args in calls], done_reason)


class FakeBackend:
    """Returns scripted replies (or raises scripted exceptions) and records every request."""

    def __init__(self, *script: ChatReply | Exception) -> None:
        self.script = list(script)
        self.requests: list[list[dict[str, Any]]] = []

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatReply:
        self.requests.append(copy.deepcopy(messages))
        if not self.script:
            raise AssertionError("FakeBackend ran out of scripted replies")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# --- Stub Ollama HTTP server ----------------------------------------------------------


class OllamaStub:
    """A minimal fake of Ollama's HTTP API, listening on 127.0.0.1 on a free port.

    `chat_responses` is a queue of (status_code, body) pairs; body may be a dict
    (sent as JSON) or a raw string (to simulate malformed responses).
    """

    def __init__(self) -> None:
        self.version = "0.12.0"
        self.models = {"qwen3:4b": ["completion", "tools", "thinking"]}
        self.chat_responses: list[tuple[int, Any]] = []
        self.chat_requests: list[dict[str, Any]] = []
        self.delay_seconds = 0.0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output quiet
                pass

            def _send(self, status: int, body: Any) -> None:
                data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/api/version":
                    self._send(200, {"version": stub.version})
                elif self.path == "/api/tags":
                    self._send(200, {"models": [{"model": name, "name": name} for name in stub.models]})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/show":
                    name = payload.get("model")
                    if name in stub.models:
                        self._send(200, {"capabilities": stub.models[name], "model_info": {}})
                    else:
                        self._send(404, {"error": f"model '{name}' not found"})
                elif self.path == "/api/chat":
                    stub.chat_requests.append(payload)
                    if stub.delay_seconds:
                        time.sleep(stub.delay_seconds)
                    status, body = (
                        stub.chat_responses.pop(0) if stub.chat_responses else (500, {"error": "no scripted response"})
                    )
                    self._send(status, body)
                else:
                    self._send(404, {"error": "not found"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def queue_chat(
        self, content: str = "", tool_calls: list[tuple[str, dict]] | None = None, status: int = 200
    ) -> None:
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = [{"function": {"name": n, "arguments": a}} for n, a in tool_calls]
        self.chat_responses.append(
            (
                status,
                {
                    "model": "qwen3:4b",
                    "created_at": "2026-01-01T00:00:00Z",
                    "message": message,
                    "done": True,
                    "done_reason": "stop",
                },
            )
        )


def free_port() -> int:
    """A port on 127.0.0.1 with nothing listening on it."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
