# Testing AgentForge Local AI

This file records **how** AgentForge is tested and **what was actually observed**. It
keeps five kinds of evidence apart:

- unit tests;
- integration tests;
- browser (UI) tests;
- manual checks;
- tests that have **not** been performed.

## How to run the tests

```bash
.venv/bin/python -m pytest                     # everything available; no model needed
.venv/bin/python -m pytest -v tests/test_web.py
.venv/bin/python -m pytest -m ui -v            # browser tests (needs: pip install playwright && python -m playwright install chromium)
AGENTFORGE_LIVE_TESTS=1 .venv/bin/python -m pytest -m live -v   # real Ollama + model
```

- **Isolation:** a fixture isolates every test from your own `.env` and `AGENTFORGE_*` variables, and notes are written to temporary folders.
- **No real model in the default suite:** the model is replaced either by `FakeBackend` (scripted replies) or by `OllamaStub`, a small HTTP server on 127.0.0.1 that imitates Ollama's API (`tests/helpers.py`).

## Test inventory: 222 tests

| File | Tests | Type | What it covers |
|---|---|---|---|
| `test_calculator.py` | 41 | Unit | Valid expressions and formatting; **division by zero**; rejection of names, calls, attributes, strings, booleans, complex numbers, comparisons and code injection; invalid syntax; helpful hints for `^` and commas; huge powers refused in < 1 s; length limit |
| `test_notes.py` | 29 | Unit | **Create, read, list and search**; name normalisation; never overwrite; missing note; path traversal and symlink escape; size and empty-content limits; **storage failures** (notes path is a file, disk full with no partial note left behind, permission denied on save, read and search) |
| `test_tools.py` | 28 | Unit | Tool set and schemas; no code or shell tools; **unknown tool rejection**; exact names; **input validation** (missing, unexpected, wrong type, bool, non-object, too long); JSON-string arguments; contained crashes; truncation |
| `test_agent.py` | 21 | Unit (fake model) | Direct answer; tool call then answer; multi-step chain; unknown tool from the model; corrected arguments; **malformed model output** (bad JSON, wrong types); **iteration limit**; repeat detection; per-step cap; empty or length-limited answers; input limits; **runtime unavailable with no fallback**; history |
| `test_config.py` | 34 | Unit | Defaults; `.env` precedence; invalid values; remote Ollama refused unless opted in; **cloud models refused**; loopback detection; `.env.example` matches the defaults |
| `test_llm.py` | 22 | 8 unit + 14 integration | Error translation (connection, **timeout**, 404, no tools, no thinking, HTTP 500, bad JSON); reply parsing. Over HTTP to the stub: full agent run and request format, **runtime unavailable**, model missing, **malformed responses**, HTTP 500, **timeout**, health check, model listing (cloud models excluded) |
| `test_offline.py` | 6 | Integration + static | **Socket-level guard**: a full agent run opens only 127.0.0.1 connections; proxy variables ignored; **no hidden cloud fallback**; no cloud SDK in dependencies; no remote URLs in the Python, HTML or JS sources; no `eval`, `exec`, `subprocess` or `os.system` (AST scan) |
| `test_cli.py` | 11 | Integration | **Application startup** (`python -m agentforge`); `--check` with the service down and up; one-shot answer; no traceback on errors; exit codes; `--model` validation; chat-loop commands |
| `test_web.py` | 22 | Integration (HTTP) | Page and static files with security headers; traversal and unknown paths → 404; **foreign Host → 403; cross-site Origin → 403**; JSON-only, size limit → 415, 400, 413; chat with tool steps; input errors; **runtime down → 503 with hint**; busy → 409; direct tool endpoint (unknown tool rejected); status, tools and models; model switching (cloud refused, not-downloaded refused); reset; loopback binding; `--web` port in use |
| `test_ui_browser.py` | 5 | Browser (Playwright, optional) | **Critical UI behaviour** in headless Chromium: page loads with runtime status and no JS errors; chat shows answer and tool steps; **model output shown as text, not HTML** (an `<img onerror>` answer); direct tool panel and notes panel; suggestion chip and *New conversation* |
| `test_live_ollama.py` | 3 | Live (optional) | Real model: calculator use, note round-trip, no-tool answer. Skipped unless `AGENTFORGE_LIVE_TESTS=1` |

**Checking that the tests can fail.** These checks were done during development by
deliberately breaking the code:

- Switching the Ollama client back to `trust_env=True` made the proxy test fail.
- Disabling only the calculator's exponent check did not make the huge-power tests fail, because the separate magnitude check still blocked them. The redundancy is intentional.

## Observed results

### Automated tests (28 October 2026)

| Environment | Install | Result |
|---|---|---|
| Linux aarch64 sandbox on the developer's computer, Python 3.12.15, fresh clone in a path containing a space and `:` | `uv sync --extra dev` (from `uv.lock`) | **214 passed, 4 skipped**: 3 live tests (no Ollama), and the browser-test module (Playwright not installed) |
| Same sandbox, Python 3.10.12 | `python3 -m venv` + `pip install -e ".[dev]"` | **214 passed, 4 skipped** (same reasons) |
| Linux x86_64 development container, Python 3.13, Chromium via Playwright 1.63 | `pip install -e .` + pytest + playwright | **219 passed, 3 skipped**: the 5 browser tests ran and passed; the 3 live tests were skipped |

Package versions in the sandbox runs: `ollama` 0.6.3, `httpx` 0.28.1, `python-dotenv` 1.2.4, `pytest` 9.2.0.

### Static analysis, security and dependency checks (29 October 2026)

These tools are not part of the default dependencies. Install them with
`.venv/bin/pip install ruff mypy bandit pip-audit`.

| Command | Result |
|---|---|
| `ruff check agentforge tests` (rules E, F, W, I, B, UP, S) | All checks passed |
| `ruff format --check agentforge tests` | 24 files already formatted |
| `mypy agentforge` | Success: no issues found in 11 source files |
| `bandit -r agentforge` | No issues identified (0 high, 0 medium) |
| `pip-audit` (installed environment) | No known vulnerabilities found. The project itself is not on PyPI, so it was not audited |

The first run of these tools found issues that were then fixed:

- import order and long lines;
- formatting of 13 files;
- two type errors: untyped operator tables in `calculator.py`, and a dynamically created handler class in `web.py`.

After the fixes, the automated suite was re-run: **219 passed, 3 skipped** in the development container.

### Manual checks (performed, without a language model)

**Terminal**, in the sandbox with no Ollama server:

| Check | Observed |
|---|---|
| `--check` with Ollama not running | `Ollama reachable: no`, then ``Problem: Cannot connect to Ollama at http://127.0.0.1:11434. Start Ollama (open the Ollama app, or run `ollama serve` ...)``, exit code 2 |
| One-shot question with Ollama not running | `Error: Cannot connect to Ollama ...`, a hint, exit code 2, no traceback |
| Remote Ollama URL | `Configuration error: ... points to another machine (192.168.1.50).`, exit code 1 |
| `--model gpt-oss:120b-cloud` | `Configuration error: ... is an Ollama cloud model ...`, exit code 1 |
| `/run calculator 0.15 * 1240 + 37.5`, `1/0`, `9**9**9**9` | `223.5`, `Division by zero is not allowed.`, `Exponents larger than 1000 are not allowed.` |
| `/run shell {...}` | `Unknown tool 'shell'. Allowed tools: ...` |
| `/run calculator {"expression": "__import__('os').system('ls')"}` | `Only numbers, + - * / // % **, and parentheses are allowed.` |
| Notes: save, read, list, search, overwrite attempt | Saved; text read back; listed; found; `A note named 'viva' already exists ...` |
| Git ignores user data | `git status` did not list `data/` |
| Install paths | `uv sync` and `pip install -e` succeeded. `uv run` **failed** in a path containing `:` and worked in a path without one (see INSTALLATION.md) |

**Web interface (`agentforge --web --port 8799`)**, in the sandbox with no Ollama server:

| Check | Observed |
|---|---|
| Startup message | `AgentForge Local AI v1.0.0 web interface` / `Open http://127.0.0.1:8799/ ... Only this computer can connect.` |
| `GET /` | `<title>AgentForge Local AI</title>` |
| `GET /api/status` | `reachable: False`, `ok: False`, problem `Cannot connect to Ollama at http://127.0.0.1:11434. ...` |
| `POST /api/tool` calculator `0.15 * 1240 + 37.5` | `{"ok": true, "output": "223.5"}` |
| `POST /api/tool` with tool `shell` | `{"ok": false, "output": "Unknown tool 'shell'. ..."}` |
| `POST /api/chat` with Ollama down | HTTP 503, `"kind": "LLMUnavailableError"` with the start-Ollama hint |
| Foreign `Host` header / cross-site `Origin` | HTTP 403 / HTTP 403 |

**Screenshots** (development container, Chromium): see `docs/images/`. One screenshot uses
the scripted stub model server, and its caption in the README says so.

## Not performed

| Test | Reason | How to do it |
|---|---|---|
| **End-to-end run with a real model** (`qwen3:4b` or any other) | No Ollama model could be downloaded in either development environment: the model registry was not reachable, and the local sandbox has 3 GB of RAM | Install Ollama, `ollama pull qwen3:4b`, follow the demonstration script in USER_GUIDE.md |
| Live automated tests | Same reason | `AGENTFORGE_LIVE_TESTS=1 .venv/bin/python -m pytest -m live -v` |
| Verification that `qwen3:4b` selects tools reliably | Needs the real model and an experimental design | See PROJECT_REPORT.md §7 |
| Fully offline run with Wi-Fi switched off | Needs the real model | Demonstration steps 1–4 with Wi-Fi off |
| macOS and Windows | Only Linux was available. The code uses portable standard-library features | Run the suite on your Mac |
| Browser tests on the developer's computer | Playwright was not installed there | See the command above |

## Your own results

Fill this in after running on your laptop:

| Date | Machine / OS / RAM | Ollama | Model | Command | Result |
|---|---|---|---|---|---|
| | | | `qwen3:4b` | `--check` | |
| | | | `qwen3:4b` | `pytest -m live` | |
| | | | `qwen3:4b` | Demonstration steps 1–6 | |
