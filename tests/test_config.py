"""Unit tests for configuration loading and validation."""

from pathlib import Path

import pytest

from agentforge.config import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, is_cloud_model, is_loopback_url, load_settings
from agentforge.errors import ConfigError

NO_ENV_FILE = {"AGENTFORGE_ENV_FILE": "/nonexistent/.env"}


def load(**values):
    return load_settings({**NO_ENV_FILE, **values})


def test_safe_defaults():
    settings = load()
    assert settings.model == DEFAULT_MODEL == "qwen3:4b"
    assert settings.ollama_url == DEFAULT_OLLAMA_URL == "http://127.0.0.1:11434"
    assert settings.allow_remote_ollama is False
    assert settings.max_iterations == 6
    assert settings.think is True and settings.num_gpu is None


def test_environment_overrides():
    settings = load(
        AGENTFORGE_MODEL="llama3.2:3b",
        AGENTFORGE_OLLAMA_URL="http://localhost:11500/",
        AGENTFORGE_MAX_ITERATIONS="3",
        AGENTFORGE_TIMEOUT_SECONDS="30.5",
        AGENTFORGE_THINK="false",
        AGENTFORGE_NUM_GPU="0",
        AGENTFORGE_HISTORY_TURNS="0",
    )
    assert settings.model == "llama3.2:3b"
    assert settings.ollama_url == "http://localhost:11500"  # trailing slash removed
    assert settings.max_iterations == 3 and settings.request_timeout == 30.5
    assert settings.think is False and settings.num_gpu == 0 and settings.history_turns == 0


def test_env_file_is_read_and_real_env_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AGENTFORGE_MODEL=qwen3:1.7b\nAGENTFORGE_MAX_ITERATIONS=4\n")
    settings = load_settings({"AGENTFORGE_ENV_FILE": str(env_file), "AGENTFORGE_MAX_ITERATIONS": "5"})
    assert settings.model == "qwen3:1.7b" and settings.max_iterations == 5


def test_blank_values_fall_back_to_defaults():
    assert load(AGENTFORGE_MODEL="", AGENTFORGE_NUM_GPU="  ").model == DEFAULT_MODEL


def test_relative_data_dir_is_resolved(tmp_path):
    assert load(AGENTFORGE_DATA_DIR="mydata").data_dir.name == "mydata"
    assert load(AGENTFORGE_DATA_DIR=str(tmp_path)).notes_dir == Path(tmp_path) / "notes"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AGENTFORGE_MAX_ITERATIONS", "0"),
        ("AGENTFORGE_MAX_ITERATIONS", "100"),
        ("AGENTFORGE_MAX_ITERATIONS", "six"),
        ("AGENTFORGE_TIMEOUT_SECONDS", "-1"),
        ("AGENTFORGE_TIMEOUT_SECONDS", "fast"),
        ("AGENTFORGE_THINK", "maybe"),
        ("AGENTFORGE_MODEL", "bad model name!"),
        ("AGENTFORGE_OLLAMA_URL", "ftp://127.0.0.1"),
        ("AGENTFORGE_OLLAMA_URL", "not a url"),
    ],
)
def test_invalid_values_are_rejected(key, value):
    with pytest.raises(ConfigError):
        load(**{key: value})


@pytest.mark.parametrize("url", ["http://192.168.1.20:11434", "https://ollama.example.com", "http://10.0.0.5:11434"])
def test_remote_ollama_is_refused_by_default(url):
    with pytest.raises(ConfigError, match="another machine") as caught:
        load(AGENTFORGE_OLLAMA_URL=url)
    assert "AGENTFORGE_ALLOW_REMOTE_OLLAMA" in caught.value.hint


def test_remote_ollama_needs_explicit_opt_in():
    settings = load(AGENTFORGE_OLLAMA_URL="http://192.168.1.20:11434", AGENTFORGE_ALLOW_REMOTE_OLLAMA="true")
    assert settings.allow_remote_ollama and settings.ollama_url == "http://192.168.1.20:11434"


@pytest.mark.parametrize(
    "model", ["gpt-oss:120b-cloud", "qwen3-coder:480b-cloud", "deepseek-v3.1:671b-cloud", "kimi-k2:cloud"]
)
def test_cloud_models_are_refused(model):
    assert is_cloud_model(model)
    with pytest.raises(ConfigError, match="cloud model"):
        load(AGENTFORGE_MODEL=model)


@pytest.mark.parametrize("model", ["qwen3:4b", "llama3.2:3b", "qwen3:1.7b", "mistral"])
def test_local_models_are_not_cloud(model):
    assert not is_cloud_model(model)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1:11434", True),
        ("http://localhost:11434", True),
        ("http://[::1]:11434", True),
        ("http://127.5.5.5", True),
        ("http://192.168.0.2:11434", False),
        ("http://ollama.com", False),
        ("http://localhost.evil.com", False),
    ],
)
def test_loopback_detection(url, expected):
    assert is_loopback_url(url) is expected


def test_env_example_is_valid_and_matches_defaults():
    example = Path(__file__).resolve().parent.parent / ".env.example"
    from_example = load_settings({"AGENTFORGE_ENV_FILE": str(example)})
    assert from_example == load()
