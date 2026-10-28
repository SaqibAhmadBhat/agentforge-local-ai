"""Talking to the local language model (served by Ollama).

`ChatBackend` is the small interface the agent depends on. `OllamaBackend`
implements it with the official `ollama` Python package; tests use a fake
backend instead, so they never need a downloaded model.

Offline / privacy safeguards in this module:
- requests go only to the configured Ollama URL (loopback by default, see config.py);
- HTTP proxy environment variables are ignored (`trust_env=False`), so local
  traffic is never routed through a proxy;
- redirects are not followed;
- every failure becomes a specific LLMError. There is NO fallback to a cloud API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
import ollama

from agentforge.config import Settings, is_cloud_model, is_loopback_url
from agentforge.errors import (
    LLMError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelCapabilityError,
    ModelNotFoundError,
)

# Ollama added the `think` request option in 0.9.0; tool calling is older.
MIN_OLLAMA_VERSION = (0, 9, 0)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class ToolCallRequest:
    """A tool call proposed by the model. Arguments are unvalidated at this point."""

    name: str
    arguments: Any


@dataclass(frozen=True)
class ChatReply:
    """One assistant turn: either final text, or one or more tool calls."""

    content: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    done_reason: str | None = None  # "stop", or "length" if the output limit was hit


class ChatBackend(Protocol):
    """Anything that can send a conversation plus tool schemas to a model."""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatReply: ...


@dataclass
class ServiceStatus:
    """Result of a health check against the Ollama server."""

    url: str
    reachable: bool = False
    server_version: str | None = None
    model_available: bool = False
    capabilities: list[str] | None = None
    problems: list[str] = field(default_factory=list)  # things that stop AgentForge working
    warnings: list[str] = field(default_factory=list)  # things the user should know about

    @property
    def ok(self) -> bool:
        return self.reachable and self.model_available and not self.problems


def strip_thinking(text: str) -> str:
    """Remove any <think>...</think> reasoning a model leaked into its answer."""
    return _THINK_BLOCK.sub("", text).strip()


def parse_version(text: str) -> tuple[int, ...]:
    """'0.12.3-rc1' -> (0, 12, 3). Missing or odd parts become 0."""
    parts = re.findall(r"\d+", text.split("-")[0])[:3]
    return tuple(int(p) for p in parts) + (0,) * (3 - len(parts))


class OllamaBackend:
    """ChatBackend implementation for a local Ollama server."""

    def __init__(self, settings: Settings, client: ollama.Client | None = None) -> None:
        self.settings = settings
        self._client = client or ollama.Client(
            host=settings.ollama_url,
            timeout=settings.request_timeout,
            trust_env=False,  # ignore HTTP(S)_PROXY: local traffic must stay local
            follow_redirects=False,
        )

    # -- chat -------------------------------------------------------------------------

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ChatReply:
        """Send the conversation to the model and return its reply.

        Raises:
            LLMError subclass: on any connection, timeout, model or protocol problem.
        """
        options: dict[str, Any] = {"num_predict": self.settings.max_output_tokens}
        if self.settings.num_gpu is not None:
            options["num_gpu"] = self.settings.num_gpu
        try:
            response = self._client.chat(
                model=self.settings.model,
                messages=messages,
                tools=tools or None,
                think=self.settings.think,
                options=options,
            )
        except Exception as exc:  # noqa: BLE001 - translated into specific errors below
            raise self._translate_error(exc) from exc
        return self._parse_reply(response)

    @staticmethod
    def _parse_reply(response: Any) -> ChatReply:
        message = getattr(response, "message", None)
        if message is None:
            raise LLMResponseError("The model service returned a reply without a message.")
        calls = []
        for call in getattr(message, "tool_calls", None) or []:
            function = getattr(call, "function", None)
            calls.append(
                ToolCallRequest(
                    name=str(getattr(function, "name", "") or ""),
                    arguments=getattr(function, "arguments", None),
                )
            )
        content = getattr(message, "content", None) or ""
        if not isinstance(content, str):
            raise LLMResponseError("The model service returned non-text content.")
        return ChatReply(
            content=strip_thinking(content),
            tool_calls=calls,
            done_reason=getattr(response, "done_reason", None),
        )

    def _translate_error(self, exc: Exception) -> LLMError:
        """Map low-level exceptions to AgentForge errors with actionable hints."""
        url, model = self.settings.ollama_url, self.settings.model
        if isinstance(exc, LLMError):
            return exc
        if isinstance(exc, httpx.TimeoutException):
            return LLMTimeoutError(
                f"The model did not answer within {self.settings.request_timeout:g} seconds.",
                hint="The first request loads the model and is slow on CPU. Try again, use a smaller "
                "model, set AGENTFORGE_THINK=false, or raise AGENTFORGE_TIMEOUT_SECONDS.",
            )
        # The ollama package turns httpx.ConnectError into the built-in ConnectionError.
        if isinstance(exc, (ConnectionError, httpx.TransportError)):
            return LLMUnavailableError(
                f"Cannot connect to Ollama at {url}.",
                hint="Start Ollama (open the Ollama app, or run `ollama serve` in another terminal), "
                "then try again. Install it from https://ollama.com/download if needed.",
            )
        if isinstance(exc, httpx.HTTPStatusError):
            return LLMResponseError(f"Ollama returned HTTP {exc.response.status_code} for {exc.request.url.path}.")
        if isinstance(exc, ollama.ResponseError):
            text = str(exc.error)
            lowered = text.lower()
            if exc.status_code == 404 or "not found" in lowered:
                return ModelNotFoundError(
                    f"The model '{model}' is not available in Ollama ({text}).",
                    hint=f"Download it once with: ollama pull {model}",
                )
            if "does not support tools" in lowered:
                return ModelCapabilityError(
                    f"The model '{model}' does not support tool calling.",
                    hint="Use a tool-capable model such as qwen3:4b (set AGENTFORGE_MODEL).",
                )
            if "does not support thinking" in lowered:
                return ModelCapabilityError(
                    f"The model '{model}' does not support thinking mode.",
                    hint="Set AGENTFORGE_THINK=false in your .env file.",
                )
            return LLMResponseError(f"Ollama returned an error (HTTP {exc.status_code}): {text}")
        if isinstance(exc, ValueError):  # bad JSON or a reply that fails the SDK's schema
            return LLMResponseError("The model service returned a malformed response.")
        return LLMResponseError(f"Unexpected error talking to Ollama: {type(exc).__name__}: {exc}")

    # -- model selection --------------------------------------------------------------

    def list_models(self) -> list[str]:
        """Names of the models already downloaded into the local Ollama (cloud models excluded).

        Raises:
            LLMError subclass: if Ollama cannot be reached.
        """
        try:
            response = self._client.list()
        except Exception as exc:  # noqa: BLE001 - translated below
            raise self._translate_error(exc) from exc
        names = [getattr(m, "model", None) or "" for m in getattr(response, "models", None) or []]
        return sorted(n for n in names if n and not is_cloud_model(n))

    # -- health check -----------------------------------------------------------------

    def check(self, timeout: float = 5.0) -> ServiceStatus:
        """Check the server is reachable, recent enough, and has the model with tool support.

        Never raises; problems are listed in the returned status.
        """
        status = ServiceStatus(url=self.settings.ollama_url)
        try:
            response = httpx.get(
                f"{self.settings.ollama_url}/api/version",
                timeout=timeout,
                trust_env=False,
                follow_redirects=False,
            )
            response.raise_for_status()
            status.server_version = str(response.json().get("version", "unknown"))
            status.reachable = True
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            error = self._translate_error(exc)
            status.problems.append(f"{error} {error.hint}".strip())
            return status

        if status.server_version != "unknown" and parse_version(status.server_version) < MIN_OLLAMA_VERSION:
            minimum = ".".join(map(str, MIN_OLLAMA_VERSION))
            status.problems.append(
                f"Ollama {status.server_version} is older than {minimum}. Update Ollama from https://ollama.com/download."
            )

        try:
            info = self._client.show(self.settings.model)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            error = self._translate_error(exc)
            status.problems.append(f"{error} {error.hint}".strip())
            return status

        status.model_available = True
        capabilities = getattr(info, "capabilities", None)
        status.capabilities = list(capabilities) if capabilities else None
        if status.capabilities is not None:
            if "tools" not in status.capabilities:
                status.problems.append(
                    f"The model '{self.settings.model}' does not support tool calling. Use a model such as qwen3:4b."
                )
            if self.settings.think and "thinking" not in status.capabilities:
                status.problems.append(
                    f"The model '{self.settings.model}' does not support thinking. Set AGENTFORGE_THINK=false."
                )
        if not is_loopback_url(self.settings.ollama_url):
            status.warnings.append(
                "Warning: Ollama is on another machine, so prompts leave this computer "
                "(AGENTFORGE_ALLOW_REMOTE_OLLAMA=true)."
            )
        return status
