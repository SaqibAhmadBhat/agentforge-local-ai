"""Configuration: read settings from environment variables and an optional .env file.

All settings use the `AGENTFORGE_` prefix. Real environment variables take
precedence over values in the .env file. Every value is validated once at
startup so mistakes are reported clearly instead of failing halfway through a chat.

There are no API keys: AgentForge only talks to a local Ollama server.
"""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

from agentforge.errors import ConfigError

# Folder that contains pyproject.toml when AgentForge runs from a source checkout.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODEL = "qwen3:4b"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"

_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


def default_base_dir() -> Path:
    """Where .env and data/ live by default.

    The project folder when running from a source checkout (the normal case for
    this course project); otherwise a `.agentforge` folder in the user's home.
    """
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        return PROJECT_ROOT
    return Path.home() / ".agentforge"


@dataclass(frozen=True)
class Settings:
    """All tunable settings, with safe defaults."""

    model: str = DEFAULT_MODEL
    ollama_url: str = DEFAULT_OLLAMA_URL
    allow_remote_ollama: bool = False
    request_timeout: float = 180.0
    max_iterations: int = 6
    max_tool_calls_per_step: int = 4
    max_input_chars: int = 4000
    max_tool_result_chars: int = 2000
    max_output_tokens: int = 2048
    history_turns: int = 4
    think: bool = True
    num_gpu: int | None = None
    data_dir: Path = PROJECT_ROOT / "data"
    web_port: int = 8765

    @property
    def notes_dir(self) -> Path:
        """Folder holding one text file per note."""
        return self.data_dir / "notes"


def is_loopback_url(url: str) -> bool:
    """True if the URL's host is this computer (localhost, 127.x.x.x or ::1)."""
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_cloud_model(model: str) -> bool:
    """True for Ollama cloud models (e.g. 'gpt-oss:120b-cloud').

    Ollama forwards these to ollama.com instead of running them locally, which
    would break AgentForge's offline guarantee, so they are refused.
    """
    name = model.lower()
    tag = name.split(":", 1)[1] if ":" in name else ""
    return tag == "cloud" or tag.endswith("-cloud") or name.endswith("-cloud")


def _parse_bool(key: str, raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE_WORDS:
        return True
    if value in _FALSE_WORDS:
        return False
    raise ConfigError(f"{key} must be true or false, got {raw!r}.")


def _parse_int(key: str, raw: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw.strip())
    except ValueError:
        raise ConfigError(f"{key} must be a whole number, got {raw!r}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}, got {value}.")
    return value


def _parse_float(key: str, raw: str, minimum: float, maximum: float) -> float:
    try:
        value = float(raw.strip())
    except ValueError:
        raise ConfigError(f"{key} must be a number, got {raw!r}.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}, got {value}.")
    return value


def validate_model(model: str) -> str:
    model = model.strip()
    if not _MODEL_NAME_PATTERN.match(model):
        raise ConfigError(
            f"AGENTFORGE_MODEL {model!r} is not a valid Ollama model name.",
            hint="Use a name exactly as shown by `ollama list`, for example qwen3:4b.",
        )
    if is_cloud_model(model):
        raise ConfigError(
            f"AGENTFORGE_MODEL {model!r} is an Ollama cloud model, which runs on remote servers.",
            hint="AgentForge only uses models that run on your own computer. Pick a local model such as qwen3:4b.",
        )
    return model


def _validate_url(url: str, allow_remote: bool) -> str:
    url = url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError(
            f"AGENTFORGE_OLLAMA_URL {url!r} is not a valid http(s) URL.",
            hint=f"The default is {DEFAULT_OLLAMA_URL}.",
        )
    if not allow_remote and not is_loopback_url(url):
        raise ConfigError(
            f"AGENTFORGE_OLLAMA_URL points to another machine ({parsed.hostname}).",
            hint=(
                "AgentForge keeps your prompts on this computer by default. If you really want to "
                "use an Ollama server elsewhere on your network, set AGENTFORGE_ALLOW_REMOTE_OLLAMA=true."
            ),
        )
    return url


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Build validated Settings from the environment and the .env file.

    Args:
        environ: Variables to read. Defaults to `os.environ`. The .env file named by
            AGENTFORGE_ENV_FILE (default: `<base dir>/.env`) is read too, with lower priority.

    Raises:
        ConfigError: if any value is invalid.
    """
    environ = dict(os.environ if environ is None else environ)
    base_dir = default_base_dir()
    env_file = Path(environ.get("AGENTFORGE_ENV_FILE") or base_dir / ".env")
    file_values = {k: v for k, v in dotenv_values(env_file).items() if v is not None} if env_file.is_file() else {}
    values = {**file_values, **environ}

    def get(key: str) -> str | None:
        raw = values.get(key)
        return raw if raw is not None and raw.strip() != "" else None

    def int_setting(key: str, default: int, minimum: int, maximum: int) -> int:
        return _parse_int(key, get(key) or str(default), minimum, maximum)

    def bool_setting(key: str, default: bool) -> bool:
        return _parse_bool(key, get(key) or str(default))

    d = Settings()  # defaults
    allow_remote = bool_setting("AGENTFORGE_ALLOW_REMOTE_OLLAMA", d.allow_remote_ollama)

    data_dir = Path(get("AGENTFORGE_DATA_DIR") or "data").expanduser()
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir

    num_gpu_raw = get("AGENTFORGE_NUM_GPU")
    timeout_raw = get("AGENTFORGE_TIMEOUT_SECONDS") or str(d.request_timeout)

    return Settings(
        model=validate_model(get("AGENTFORGE_MODEL") or d.model),
        ollama_url=_validate_url(get("AGENTFORGE_OLLAMA_URL") or d.ollama_url, allow_remote),
        allow_remote_ollama=allow_remote,
        request_timeout=_parse_float("AGENTFORGE_TIMEOUT_SECONDS", timeout_raw, 1, 3600),
        max_iterations=int_setting("AGENTFORGE_MAX_ITERATIONS", d.max_iterations, 1, 20),
        max_tool_calls_per_step=int_setting("AGENTFORGE_MAX_TOOL_CALLS_PER_STEP", d.max_tool_calls_per_step, 1, 10),
        max_input_chars=int_setting("AGENTFORGE_MAX_INPUT_CHARS", d.max_input_chars, 100, 50_000),
        max_tool_result_chars=int_setting("AGENTFORGE_MAX_TOOL_RESULT_CHARS", d.max_tool_result_chars, 200, 20_000),
        max_output_tokens=int_setting("AGENTFORGE_MAX_OUTPUT_TOKENS", d.max_output_tokens, 64, 32_768),
        history_turns=int_setting("AGENTFORGE_HISTORY_TURNS", d.history_turns, 0, 20),
        think=bool_setting("AGENTFORGE_THINK", d.think),
        num_gpu=_parse_int("AGENTFORGE_NUM_GPU", num_gpu_raw, 0, 1000) if num_gpu_raw else None,
        data_dir=data_dir,
        web_port=int_setting("AGENTFORGE_WEB_PORT", d.web_port, 1024, 65535),
    )
