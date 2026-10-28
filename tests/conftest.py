"""Shared test fixtures.

No test in the default suite needs Ollama or a downloaded model: the model is
replaced by `FakeBackend` (scripted replies) or by `OllamaStub`, a tiny HTTP
server on 127.0.0.1 that imitates Ollama's API (see helpers.py).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from helpers import OllamaStub

from agentforge.config import Settings


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make sure a developer's own .env or AGENTFORGE_* variables cannot affect tests."""
    for key in list(os.environ):
        if key.startswith("AGENTFORGE_") or key in {"OLLAMA_HOST", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AGENTFORGE_ENV_FILE", str(tmp_path / "no-such.env"))
    monkeypatch.setenv("AGENTFORGE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", request_timeout=5)


@pytest.fixture
def ollama_stub():
    stub = OllamaStub()
    stub.thread.start()
    yield stub
    stub.server.shutdown()
    stub.server.server_close()
