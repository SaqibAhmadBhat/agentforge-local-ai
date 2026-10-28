# Viva Preparation Guide: AgentForge Local AI

Short answers to give in your own words, each with the file to point at.

## 1. The 30-second pitch

AgentForge Local AI is an AI agent that runs entirely on my laptop. A small language
model, `qwen3:4b` running in Ollama, reads my request and decides whether a tool is
needed. My code validates that decision and runs a deterministic tool: calculator, notes,
date/time or word count. The result goes back to the model for the final answer. There
is no cloud API, every action is validated, and the loop has hard limits. It has a
terminal and a local web interface. I started from an MIT-licensed prototype, audited it,
and rebuilt it with validation, error handling, privacy safeguards and 222 tests. I
undertook it as part of the AI/ML EWB internship course.

## 2. Architecture (draw this)

```text
User → Terminal (cli.py) or Web UI (web.py, 127.0.0.1)
          ↓
     Agent loop (agent.py) ⇄ Model via Ollama (llm.py → 127.0.0.1:11434)
          ↓ proposed tool call
     ToolRegistry (tools.py): allow-list → validate → run → truncate
          ↓
     calculator.py · notes.py (data/notes) · date/time · word count · help
```

`config.py` validates the settings and enforces the offline rules.

## 3. Key concepts

**Local inference.**

- The model's weights are loaded by the Ollama server on my own machine, and text generation happens on my CPU or GPU.
- AgentForge sends HTTP requests to `127.0.0.1`, a loopback address that never leaves the computer.
- The internet is needed only to install software and to download the weights once.

**Small language model (SLM).**

- A language model with a few billion parameters or fewer. `qwen3:4b` has about 4 billion, and its file is about 2.5 GB.
- Small enough for a laptop. Less capable than large cloud models, which is exactly why exact tasks are delegated to tools.

**Tool calling.**

- The request includes JSON schemas describing each tool.
- A tool-capable model can answer with a structured call, e.g. `{"name": "calculator", "arguments": {"expression": "0.15*1240"}}`, instead of text.
- The model never runs anything itself. It *asks*, and my code decides.

**Execution flow (`Agent.run`).**

1. Validate the input.
2. Call the model.
3. If there are no tool calls, that is the final answer.
4. Otherwise, for each call (maximum 4 per step), skip exact repeats and validate and execute the rest.
5. Append the results and repeat.
6. Hard stops: 6 model calls, two repeated identical calls, and output and size limits.

**Safety boundaries:**

- an allow-list of 8 tools, with no code or shell tool;
- argument validation before execution;
- a calculator that uses an AST and never `eval`;
- note names that cannot escape `data/notes`;
- loopback-only model URL, refused cloud models, ignored proxies, no fallback;
- a web UI bound to 127.0.0.1 with Host and Origin checks, a strict CSP, and model output inserted as text only.

**Why deterministic tools?**

- A model predicts likely text, so arithmetic, the time and file contents can come out wrong.
- Python gives the exact answer every time, and each tool can be tested.

**Chatbot vs. AI agent.**

- A chatbot only replies with text.
- An agent runs a loop in which the model can choose *actions* (tools), observe the results and continue until the goal is met.
- Agents need guardrails because actions have effects.

## 4. Model inference vs. tool execution

| | Model inference | Tool execution |
|---|---|---|
| Where | Ollama server process | AgentForge's Python process |
| Nature | Probabilistic text generation | Deterministic function |
| Output | Text, or a *request* for a tool | A verified result string |
| Failure modes | Hallucination, wrong tool, bad arguments | Validation error, expected error (e.g. division by zero) |
| Code | `llm.py` → `OllamaBackend.chat` | `tools.py` → `ToolRegistry.execute` |

## 5. Likely questions

- **Is it really offline?**
  After installation, yes. A test records every socket connection in a full agent run and fails on any non-loopback address (`test_agent_run_only_connects_to_loopback`).
- **What if the model invents a tool?**
  The registry rejects it with `Unknown tool`, nothing runs, and the model sees the error (`test_unknown_tool_from_model_is_rejected_and_reported_back`).
- **What stops infinite loops?**
  The 6-iteration limit, repeat detection and the per-step cap (`test_iteration_limit_stops_the_loop`).
- **How did you test without a model?**
  The agent depends on a `ChatBackend` interface:
  - unit tests use `FakeBackend` with scripted replies;
  - integration tests use a stub Ollama HTTP server;
  - browser tests drive the real page in headless Chromium.
- **Did you test with the real model?**
  Not yet in the development environment, and the documentation says so. I will run the live tests and the demonstration script on my laptop before presenting (TESTING.md).
- **Why is the web UI safe?**
  - It only listens on 127.0.0.1.
  - It refuses foreign Host headers and cross-site Origins.
  - It accepts JSON only, with a 64 KB limit.
  - It sends a strict CSP.
  - It inserts model output with `textContent`.

  A browser test checks that an `<img onerror>` answer is shown as text.
- **What did you change from the original?**
  See CONTRIBUTIONS.md. The upstream source is credited by URL and commit, and its MIT notice is preserved in LICENSE.
- **Limitations?**
  - Model quality has not been measured.
  - CPU inference is slow.
  - Cloud-model detection is name-based.
  - Notes are unencrypted.
  - There is a single user.
- **Was any assistance or existing code used?**
  Yes: the upstream project, credited in LICENSE and the notices. Answer any further questions honestly and in line with your course's policy.

## 6. Checklist before the viva

- [ ] `.venv/bin/python -m pytest -q` passes on your laptop.
- [ ] `ollama pull qwen3:4b`; `.venv/bin/python -m agentforge --check` shows *Ready*.
- [ ] Rehearse the demonstration in USER_GUIDE.md §5 with the real model, and record the results in TESTING.md.
- [ ] Be able to walk through `Agent.run` and `ToolRegistry.validate` line by line.
- [ ] Know the four-way comparison in PROJECT_REPORT.md §3.
