# Changelog

All notable changes to this project are documented here. Dates are in YYYY-MM-DD format.

## [1.0.0] - 2026-10-29: AgentForge Local AI

First release of AgentForge Local AI, developed from the upstream baseline below.

### Added

- **Local web interface** (`agentforge --web`):
  - conversation history with a tool-step trace, runtime status, model selection, a direct tool panel and a notes panel;
  - standard-library server bound to 127.0.0.1, with Host and Origin checks, JSON-only POST, a 64 KB body limit and a strict CSP;
  - no external assets.
- **Validating `ToolRegistry`:** allow-list, argument names, types and lengths, JSON-string arguments, result truncation, crash containment.
- **New tools:** `search_notes` and `get_help`.
- **Health check:** `--check` reports reachability, server version (≥ 0.9.0), model availability and tool/thinking capabilities.
- **Typed errors with hints:** for Ollama unavailable, timeouts, missing models, models without tool or thinking support, malformed responses and storage failures.
- **Configuration:** validated `AGENTFORGE_*` settings from the environment and `.env`. Loopback-only Ollama URL unless explicitly allowed; Ollama cloud models refused.
- **Agent loop:** repeat detection (repeats are not executed), per-step tool-call cap, input and output limits, short in-memory history.
- **Terminal commands:** `/help`, `/tools`, `/run`, `/notes`, `/status`, `/reset`, `/trace`, `/quit`; options `--model`, `--quiet`, `--debug`.
- **Tests:** 222 automated tests (unit, integration against a stub Ollama server, socket-level offline check, browser tests, optional live tests).
- **Documentation:** the `docs/` set, `CITATION.cff` and the 12-slide presentation in `presentation/`.
- **Project website:** a static landing page in `site/` (HTML and CSS only, no scripts or trackers), published with GitHub Pages from the `gh-pages` branch.

### Changed

- **Package:** `src` → `agentforge`. Command `agentforge`; distribution name `agentforge-local-ai`; Python ≥ 3.10.
- **Calculator:** exponent, magnitude and length limits; `//` supported; booleans and complex numbers rejected; clearer errors.
- **Notes:**
  - stored in `data/notes/` with normalised safe names;
  - never overwritten (`write_note` became `save_note`);
  - size limits; half-written notes removed on disk errors.
- **Ollama client:** request timeout; proxy variables ignored; redirects not followed.
- **Thinking mode:** now configurable (`AGENTFORGE_THINK`).

### Removed

- The `sandbox/` notes folder (replaced by `data/notes/`).

### Preserved

- **Upstream source:** identified by repository URL and commit `ef2d5f5` in `docs/THIRD_PARTY_NOTICES.md`.
- **Licence:** the MIT copyright notice of Bhargava Kandala.

## [0.1.0] - 2026-07-27: upstream baseline

`offline-slm-agent` by Bhargava Kandala, commit `ef2d5f5`
([Fully-Offline-AI-agent-using-SLM](https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM)).
This is a hand-written ReAct loop with six tools on `qwen3:4b` via Ollama. The version
number comes from its `pyproject.toml`.
