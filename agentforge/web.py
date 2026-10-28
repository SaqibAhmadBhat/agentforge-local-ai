"""Optional local web interface for AgentForge, built on Python's standard library only.

Start it with `agentforge --web` and open http://127.0.0.1:8765/ in a browser.

Security model (the server is meant for the person sitting at this computer only):
- it listens on 127.0.0.1, so other computers cannot connect;
- requests whose Host header is not this server are refused (DNS-rebinding defence);
- POST requests must be JSON and, when the browser sends an Origin header, it must be
  this server (cross-site request defence). No CORS headers are ever sent;
- request bodies are limited to 64 KB, and every response carries a strict
  Content-Security-Policy (no inline scripts, no external resources);
- the browser code inserts model output with textContent, never as HTML;
- prompts and notes are never written to the log.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import urlsplit

from agentforge import APP_FULL_NAME, TAGLINE, __version__
from agentforge.agent import Agent
from agentforge.config import Settings, validate_model
from agentforge.errors import ConfigError, InputError, LLMError
from agentforge.llm import ChatBackend, OllamaBackend
from agentforge.notes import NoteError, NoteStore
from agentforge.tools import build_default_registry

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "logo.svg": "image/svg+xml",
}
MAX_BODY_BYTES = 64 * 1024
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

Payload = dict[str, Any]


class WebApp:
    """The agent, tools and notes behind the web interface (one conversation per server)."""

    def __init__(
        self,
        settings: Settings,
        backend_factory: Callable[[Settings], ChatBackend] = OllamaBackend,
    ) -> None:
        self.settings = settings
        self.backend_factory = backend_factory
        self.backend = backend_factory(settings)
        self.notes = NoteStore(settings.notes_dir)
        self.registry = build_default_registry(self.notes, settings.max_tool_result_chars)
        self.agent = Agent(self.backend, self.registry, settings)
        self.busy = threading.Lock()  # one model request at a time

    # -- GET endpoints ------------------------------------------------------------------

    def status(self) -> tuple[int, Payload]:
        s = self.settings
        payload: Payload = {
            "app": {"name": APP_FULL_NAME, "version": __version__, "tagline": TAGLINE},
            "model": s.model,
            "ollama_url": s.ollama_url,
            "think": s.think,
            "max_iterations": s.max_iterations,
            "max_input_chars": s.max_input_chars,
            "notes_dir": str(s.notes_dir),
            "runtime": None,
        }
        check = getattr(self.backend, "check", None)
        if callable(check):
            status = check(timeout=3)
            payload["runtime"] = {**asdict(status), "ok": status.ok}
        return 200, payload

    def tools(self) -> tuple[int, Payload]:
        return 200, {
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": [
                        {
                            "name": p.name,
                            "type": "integer" if p.type is int else "string",
                            "description": p.description,
                            "max_length": p.max_length,
                        }
                        for p in tool.parameters
                    ],
                }
                for tool in self.registry.tools
            ]
        }

    def notes_list(self) -> tuple[int, Payload]:
        try:
            return 200, {"ok": True, "notes": self.notes.list_names(), "message": ""}
        except NoteError as exc:
            return 200, {"ok": False, "notes": [], "message": str(exc)}

    def models(self) -> tuple[int, Payload]:
        list_models = getattr(self.backend, "list_models", None)
        if not callable(list_models):
            return 200, {"models": [], "current": self.settings.model}
        try:
            return 200, {"models": list_models(), "current": self.settings.model}
        except LLMError as exc:
            return 503, _error_payload(exc)

    # -- POST endpoints -----------------------------------------------------------------

    def chat(self, body: Payload) -> tuple[int, Payload]:
        message = body.get("message")
        if not isinstance(message, str):
            return 400, {"error": "Field 'message' must be text."}
        if not self.busy.acquire(blocking=False):
            return 409, {"error": "The agent is still working on the previous request."}
        try:
            result = self.agent.run(message)
        except InputError as exc:
            return 400, _error_payload(exc)
        except LLMError as exc:
            return 503, _error_payload(exc)
        finally:
            self.busy.release()
        return 200, {
            "answer": result.answer,
            "stop_reason": result.stop_reason,
            "iterations": result.iterations,
            "steps": [asdict(step) for step in result.steps],
        }

    def run_tool(self, body: Payload) -> tuple[int, Payload]:
        """Run a tool directly (no model), through the same validation the agent uses."""
        result = self.registry.execute(body.get("tool"), body.get("arguments"))
        return 200, {"tool": result.tool, "ok": result.ok, "output": result.output}

    def reset(self, body: Payload) -> tuple[int, Payload]:
        self.agent.reset()
        return 200, {"ok": True}

    def select_model(self, body: Payload) -> tuple[int, Payload]:
        """Switch to another locally downloaded model and start a new conversation."""
        name = body.get("model")
        if not isinstance(name, str):
            return 400, {"error": "Field 'model' must be text."}
        try:
            name = validate_model(name)
        except ConfigError as exc:
            return 400, _error_payload(exc)
        status, payload = self.models()
        if status != 200:
            return status, payload
        if name not in payload["models"]:
            return 400, {"error": f"Model '{name}' is not downloaded.", "hint": f"Run: ollama pull {name}"}
        if not self.busy.acquire(blocking=False):
            return 409, {"error": "The agent is still working on the previous request."}
        try:
            self.settings = replace(self.settings, model=name)
            self.backend = self.backend_factory(self.settings)
            self.agent.backend = self.backend
            self.agent.reset()
        finally:
            self.busy.release()
        return 200, {"ok": True, "model": name}


def _error_payload(exc: Exception) -> Payload:
    return {"error": str(exc), "hint": getattr(exc, "hint", ""), "kind": type(exc).__name__}


class _Handler(BaseHTTPRequestHandler):
    """Routes HTTP requests to WebApp. Configured per server by `create_server`."""

    server_version = "AgentForge"
    sys_version = ""
    app: WebApp
    allowed_hosts: frozenset[str] = frozenset()
    allowed_origins: frozenset[str] = frozenset()

    GET_ROUTES = {"/api/status": "status", "/api/tools": "tools", "/api/notes": "notes_list", "/api/models": "models"}
    POST_ROUTES = {"/api/chat": "chat", "/api/tool": "run_tool", "/api/reset": "reset", "/api/model": "select_model"}

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        # Only the method and path are logged (at debug level); never bodies.
        logger.debug("%s %s", self.command, urlsplit(self.path).path)

    # -- responses ----------------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Payload) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _send_static(self, name: str) -> None:
        if name not in STATIC_FILES:  # allow-list: no path is ever built from user input
            self._send_json(404, {"error": "Not found."})
            return
        self._send(200, (STATIC_DIR / name).read_bytes(), STATIC_FILES[name])

    # -- request handling ---------------------------------------------------------------

    def _host_allowed(self) -> bool:
        return self.headers.get("Host", "") in self.allowed_hosts

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if not self._host_allowed():
            self._send_json(403, {"error": "Forbidden host."})
            return
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._send_static("index.html")
        elif path.startswith("/static/"):
            self._send_static(path[len("/static/") :])
        elif path in self.GET_ROUTES:
            self._send_json(*getattr(self.app, self.GET_ROUTES[path])())
        else:
            self._send_json(404, {"error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if not self._host_allowed():
            self._send_json(403, {"error": "Forbidden host."})
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.allowed_origins:
            self._send_json(403, {"error": "Cross-site requests are not allowed."})
            return
        path = urlsplit(self.path).path
        if path not in self.POST_ROUTES:
            self._send_json(404, {"error": "Not found."})
            return
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            self._send_json(415, {"error": "Send JSON (Content-Type: application/json)."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._send_json(413, {"error": f"Request body must be at most {MAX_BODY_BYTES} bytes."})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "Request body is not valid JSON."})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "Request body must be a JSON object."})
            return
        self._send_json(*getattr(self.app, self.POST_ROUTES[path])(body))


def create_server(app: WebApp, port: int) -> ThreadingHTTPServer:
    """Bind a server for `app` on 127.0.0.1:`port` (0 picks a free port)."""

    class AgentForgeHandler(_Handler):
        """Handler bound to this server's app (one class per server keeps settings separate)."""

    AgentForgeHandler.app = app
    handler = AgentForgeHandler
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    actual_port = server.server_address[1]
    hosts = frozenset({f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"})
    handler.allowed_hosts = hosts
    handler.allowed_origins = frozenset(f"http://{host}" for host in hosts)
    return server


def serve(settings: Settings, port: int | None = None, out: TextIO | None = None) -> int:
    """Run the web interface until Ctrl-C. Returns a process exit code."""
    out = out or sys.stdout
    port = port or settings.web_port
    app = WebApp(settings)
    try:
        server = create_server(app, port)
    except OSError as exc:
        print(f"Could not start the web interface on 127.0.0.1:{port}: {exc.strerror or exc}.", file=out)
        print("Hint: another program may be using that port. Try: agentforge --web --port 8766", file=out)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"{APP_FULL_NAME} v{__version__} web interface", file=out)
    print(f"Open {url} in your browser. Only this computer can connect.", file=out)
    print("Press Ctrl-C to stop.", file=out, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=out)
    finally:
        server.server_close()
    return 0
