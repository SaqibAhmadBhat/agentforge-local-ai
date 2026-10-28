# Contributions: Inherited, Modified, New and Removed

This file separates what AgentForge Local AI **inherited** from its upstream project from
what was **changed or added**. It can be checked by comparing this repository with the
upstream source at commit [`ef2d5f5`](https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM/tree/ef2d5f5).

- **Upstream:** [Fully-Offline-AI-agent-using-SLM](https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM), commit `ef2d5f5` (27 Jul 2026).
  - Licence: MIT, © 2026 Bhargava Kandala.
  - Commit author name: "Kandala Naga Venkata Surya Sree Bhargava".
  - The original source can be viewed at that commit.
- **Transformation:** October 2026, by Saqib Ahmad Bhat.

## 1. Retained ideas and approaches

| Inherited from upstream | Where it lives now |
|---|---|
| Hand-written ReAct loop (model → tool → observation → repeat), no agent framework | `agentforge/agent.py` (rewritten) |
| Ollama + `qwen3:4b`, native tool calling through the `ollama` package | `agentforge/llm.py`, default in `config.py` |
| `think=True` to keep qwen3 reasoning out of the answer | Configurable (`AGENTFORGE_THINK`) |
| Calculator that walks a restricted AST instead of using `eval()` | `agentforge/calculator.py` (extended with limits) |
| Notes confined to one folder | `agentforge/notes.py` (redesigned) |
| `current_datetime` and `word_count` tools | `agentforge/tools.py` |
| Step limit 6; tool errors returned to the model as text; a system prompt that forbids claiming unconfirmed actions | `agent.py`, `tools.py` |
| CPU fallback through `OLLAMA_NUM_GPU=0` | `AGENTFORGE_NUM_GPU` |
| MIT `LICENSE`; the tutorial credit | `LICENSE` (original notice kept, one line added); [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

## 2. Component status

| Component | Status | Summary |
|---|---|---|
| `.python-version` (3.12) | **Retained unchanged** | Used by uv |
| `src/agent.py` → `agentforge/agent.py` | **Substantially modified** | Backend interface, input limits, per-step cap, repeat detection without re-execution, history, structured `AgentResult`, stop reasons |
| `src/tools.py` → `agentforge/tools.py`, `calculator.py`, `notes.py` | **Substantially modified** | Validating `ToolRegistry`. Bounded calculator. Safe notes with no overwrite, size limits, symlink check and storage-error handling |
| `src/config.py` → `agentforge/config.py` | **Substantially modified** | Validated `AGENTFORGE_*` settings, loopback guard, cloud-model refusal |
| `src/main.py` → `agentforge/cli.py` | **Substantially modified** | New identity, `/help /tools /run /notes /status /reset /trace /quit`, `--check`, `--model`, `--web`, hints, exit codes |
| `agentforge/llm.py` | **New** | Ollama backend: timeout, proxies ignored, no redirects, typed errors, health check, model listing |
| `agentforge/web.py`, `agentforge/static/` | **New** | Local web interface: hardened standard-library server, JSON API, HTML/CSS/JS front end, logo |
| `agentforge/errors.py` | **New** | Error hierarchy with user hints |
| Tools `search_notes`, `get_help` | **New** | |
| Tool `write_note` | **Renamed and changed** | Now `save_note(name, content)`. Refuses to overwrite |
| `tests/` (222 tests) | **New** | Upstream had no tests |
| `README.md`, `CHANGELOG.md`, `CITATION.cff`, `docs/*`, `presentation/`, `site/` | **New** | Written for AgentForge Local AI |
| Upstream `README.md`, `HOW_IT_WORKS.md`, `CONCEPTS.md` | **Removed (replaced)** | They described the original application; AgentForge's own documentation replaces them |
| `docs/images/` | **New** | Screenshots captured from the running application (captions state their conditions) |
| `pyproject.toml`, `requirements*.txt`, `.env.example`, `.gitignore`, `uv.lock` | **Replaced** | Package `agentforge-local-ai`, command `agentforge`, Python ≥ 3.10, dev extras |
| `sandbox/` notes folder; package name `src` | **Removed** | Replaced by `data/notes/` and the `agentforge` package. Old notes are not migrated |

## 3. Defects and risks fixed (found in the upstream audit)

1. **Calculator freeze:** `9**9**9**9` froze the calculator. It is now refused in milliseconds.
2. **Tracebacks:** Ollama being stopped or the model missing caused a traceback. AgentForge now shows a specific message with a hint and exits with code 2.
3. **No timeout:** a request could hang forever. The timeout is now configurable (default 180 s).
4. **Silent overwrite:** `write_note` silently overwrote notes. `save_note` now refuses.
5. **No validation:** arguments were passed unchecked to `func(**arguments)`. They are now validated by the registry.
6. **Booleans as numbers:** `True + True` was accepted. Booleans are now rejected.
7. **Network gaps:** any Ollama host was accepted, and cloud models, proxies and redirects were not considered. All four are now guarded.
8. **Hard-coded thinking mode:** `think=True` was hard-coded. It is now configurable, and `--check` warns when a model lacks thinking support.

## 4. Contributions to present

1. **Audit:** auditing an open-source agent and finding its real defects.
2. **Safety layer:** an allow-list registry that validates every proposed action.
3. **Bounded loop:** iterations, repeats, per-step cap and size limits.
4. **Verifiable privacy:**
   - a loopback guard;
   - cloud-model refusal;
   - a client that ignores proxies;
   - no fallback;
   - socket-level tests.
5. **Hardened local web UI:** Host and Origin checks, CSP, text-only rendering.
6. **Testing without a model:** dependency injection, a fake model, a stub HTTP server and browser tests.
7. **Licence-compliant reuse:** notice and history preserved, changes documented.
