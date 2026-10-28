# Project Report

## AgentForge Local AI: A Privacy Focused Offline AI Agent Powered by Small Language Models

| | |
|---|---|
| **Student developer** | Saqib Ahmad Bhat, B.E. Computer Science and Engineering, Government College of Engineering, Tirunelveli, Tamil Nadu, India |
| **Academic context** | Undertaken as part of the AI/ML EWB internship course under the supervision of the EWB Courses programme |
| **Repository** | https://github.com/SaqibAhmadBhat/agentforge-local-ai |
| **Upstream project** | [Fully-Offline-AI-agent-using-SLM](https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM) by Bhargava Kandala (MIT licence), commit `ef2d5f5` |

---

## Abstract

AgentForge Local AI is an AI agent that runs a small language model (SLM) on the user's own
computer through Ollama. The model decides when to call deterministic Python tools:

- a calculator;
- local notes (save, read, list, search);
- date and time, word count, and help.

AgentForge validates and executes those calls.

The project began from an open-source prototype. It turns that prototype into a validated,
configurable and tested application with two interfaces: a terminal and a local web
interface. The original code is kept for comparison. The main contributions are:

- an allow-list tool registry that validates every model-proposed call before execution;
- a bounded agent loop;
- network safeguards that keep prompts on the user's computer;
- specific error handling for an unavailable model service;
- a hardened local web interface;
- 222 automated tests (214 core, 5 browser and 3 optional live tests).

No model-quality benchmarks were run. Section 7 states exactly what was and was not verified.

## 1. Problem statement and motivation

Most AI-agent demonstrations depend on cloud APIs. They:

- cost money;
- need a network connection;
- send user data to third parties;
- hide most of the system from the learner.

Small open-weight models can now run on laptop CPUs and support structured tool calling.
This creates an opportunity to build an agent whose *entire* pipeline (model server, agent
loop and tools) runs locally and can be inspected and tested.

**Problem.** Build a local AI agent that:

1. performs useful actions through tools;
2. never executes unsafe model-generated actions;
3. fails safely and clearly when the local model is unavailable;
4. keeps user data on the user's computer;

and that remains simple enough for an undergraduate to explain line by line.

## 2. Objectives and scope

- **O1. Local inference only:** no paid API, and no cloud fallback.
- **O2. Model proposes, code executes:** tools are deterministic, validated and allow-listed.
- **O3. Bounded execution:** iteration limits, repeat detection and size limits.
- **O4. Explicit failure modes:** service down, model missing, timeouts, malformed replies and storage failures.
- **O5. Usable interfaces:** a terminal and a local web UI, with visible runtime status and tool traces.
- **O6. Evidence:** automated tests that run without a downloaded model, and documentation that matches the code.

**Out of scope:**

- training or fine-tuning models;
- multi-user deployment;
- document retrieval beyond notes;
- quantitative model benchmarking (proposed as future work).

## 3. Background: from ML models to tool-using agents

| | Traditional ML model | Language model (LM) | Chatbot | Tool-using AI agent |
|---|---|---|---|---|
| What it is | A function learned from data for one task (classifier, regressor) | A neural network trained to predict the next token of text | An LM wrapped in a conversation interface | An LM inside a control loop that can call external tools and use their results |
| Input → output | Features → label or number | Text → probable continuation | Message (+ history) → reply | Goal → decisions, tool calls and observations → answer |
| Can act on the world? | No | No | No (text only) | Yes, through allowed tools |
| Typical weakness | Narrow; needs labelled data | Hallucination, stale knowledge, unreliable arithmetic | Same as LM | Wrong tool choice, malformed arguments, loops, unsafe actions if tools are too powerful |
| In AgentForge | Not used | `qwen3:4b` via Ollama | Terminal and web chat | `Agent.run` plus `ToolRegistry` |

The agent loop follows the **ReAct** pattern: reasoning and acting are interleaved, and
each action produces an observation that informs the next step [1]. The idea that language
models can learn *when* to call external tools was studied in **Toolformer** [2]. AgentForge
does not train a model. It relies on the native tool-calling interface of a pretrained
open-weight model (Qwen3 [3]) served by Ollama [4].

## 4. Methodology

1. **Audit the upstream code** by reading every file. Identify its behaviour, risks and gaps.
2. **Preserve provenance:**
   - record the exact upstream commit (`ef2d5f5`) as the baseline;
   - keep the MIT copyright and permission notice;
   - document inherited, modified and new components.
3. **Refactor into modules** with single responsibilities, and inject the model backend through an interface so that it can be tested.
4. **Add safety layers:** tool validation, bounded loop, network guards, a hardened web server.
5. **Test without a model:**
   - unit tests with a scripted fake model;
   - integration tests against a stub Ollama HTTP server;
   - a socket-level offline test;
   - browser tests.
6. **Document only what is implemented**, and record observed results separately from expected behaviour.

## 5. Architecture and implementation

See [ARCHITECTURE.md](ARCHITECTURE.md) for the diagrams. Modules (`agentforge/`):

| Module | Lines | Responsibility |
|---|---|---|
| `agent.py` | 216 | Loop, limits, repeat detection, history, system prompt |
| `tools.py` | 293 | Allow-list registry, schemas, validation, 8 tools |
| `llm.py` | 260 | Ollama backend, error translation, health check, model list |
| `config.py` | 207 | Validated settings, loopback guard, cloud-model refusal |
| `calculator.py` | 127 | AST arithmetic with size limits |
| `notes.py` | 145 | Safe note storage, search, storage-error handling |
| `cli.py` | 262 | Terminal interface and exit codes |
| `web.py` + `static/` | 308 + 558 | Local web server and browser front end |

**Key design decisions:**

- **Native tool calling, not a text protocol.** Qwen3 exposes structured tool calls through Ollama, so AgentForge uses them. Model unreliability is handled with validation and loop bounds rather than with a second, parsed text protocol, which would add its own failure modes.
- **Explicit JSON schemas.** Schemas are written out in the registry instead of being derived from Python signatures, so the contract the model sees is visible and tested.
- **No framework:**
  - the loop is about 100 lines of plain Python;
  - the web UI uses the standard library's `http.server` and plain JavaScript, with no CDN, so it also works offline.
- **Security for a local web server:**
  - bind to 127.0.0.1;
  - check `Host` (DNS rebinding) and `Origin` (cross-site requests);
  - accept JSON-only bodies with a size limit;
  - send a strict Content-Security-Policy;
  - insert model output with `textContent` only.

## 6. Testing

Full details are in [TESTING.md](TESTING.md).

| Type | Count | Examples |
|---|---|---|
| Unit | 153 + 8 | Calculator, notes (including storage failures), registry validation, agent loop (fake model), configuration, error translation |
| Integration | 53 | Real `ollama` client against a stub server on 127.0.0.1; CLI in-process; web API over HTTP; socket-level offline guard; static source scans |
| Browser | 5 | Playwright and Chromium: status, chat with tool steps, XSS safety, tool and notes panels, reset |
| Live (optional) | 3 | Real Ollama and model, skipped by default |

## 7. Results and evaluation

**Verified:**

- **Core suite:** 214 passed on Python 3.10.12 and 3.12.15 in a Linux sandbox on the developer's computer.
- **Full suite:** 219 passed, including the 5 browser tests, on Python 3.13 in a development container.
- **Manual checks** of the terminal and web interfaces with no model running: errors, rejections, notes and security responses (403 for foreign Host and Origin). Outputs are recorded in TESTING.md.

**Not verified:**

- **No real-model run.** No end-to-end run with a real language model was possible in the development environments: the model registry was unreachable and memory was limited. The upstream author reports verifying `qwen3:4b` tool calling, but this has **not** been independently reproduced here.
- **No metrics.** Tool-selection accuracy, latency and answer quality were not measured, so none are reported.

**Proposed evaluation (future work):**

- **Prompts:** 30–50 fixed prompts, each labelled with the expected tool or "no tool".
- **Runs:** each prompt run 5 times per configuration:
  - `qwen3:4b`, `qwen3:1.7b`, and `llama3.2:3b` with thinking off;
  - thinking on and off where supported.
- **Metrics:**
  - tool-selection accuracy;
  - argument-validation failure rate;
  - task success;
  - iterations per task;
  - latency on stated hardware.
- **Reporting:** mean ± standard deviation.

`AgentResult.steps` and `stop_reason` already expose the data needed.

## 8. Limitations

- **Model behaviour.** Real-model behaviour has not yet been verified. Small models may choose the wrong tool or answer poorly, and validation prevents unsafe actions, not wrong words.
- **Speed.** CPU inference is slow, especially with thinking mode on and on the first request.
- **Offline scope.** The offline claim covers AgentForge's own traffic. Installation, `ollama pull` and Ollama's own update checks use the internet.
- **Cloud-model detection** is name-based (`*-cloud`).
- **Scope of the tools.** Arithmetic only; notes cannot be edited or deleted; single user; one conversation per process; notes are not encrypted.

## 9. Future scope

- **Evaluation:** run the experiment in §7.
- **Notes:** note editing with confirmation.
- **Search:** keyword search over a user-chosen document folder.
- **Responses:** streaming responses in both interfaces.
- **Models without native tool calling:** an optional validated text-protocol fallback, behind the same registry.
- **Data protection:** optional encryption of the notes at rest.

## 10. Conclusion

AgentForge Local AI shows the central idea of tool-using agents in a small, inspectable
codebase. A language model is good at deciding *what* to do from natural language. Exact,
safe and auditable *doing* belongs in ordinary code with strict validation. The project's
contribution is the engineering around the model: validation, bounds, error handling,
privacy safeguards, a hardened local interface and tests. Its claims are limited to what
has been verified.

## References

1. S. Yao, J. Zhao, D. Yu, N. Du, I. Shafran, K. Narasimhan, Y. Cao, "ReAct: Synergizing Reasoning and Acting in Language Models," *ICLR*, 2023. arXiv:2210.03629.
2. T. Schick, J. Dwivedi-Yu, R. Dessì, R. Raileanu, M. Lomeli, L. Zettlemoyer, N. Cancedda, T. Scialom, "Toolformer: Language Models Can Teach Themselves to Use Tools," *NeurIPS*, 2023. arXiv:2302.04761.
3. A. Yang et al. (Qwen Team), "Qwen3 Technical Report," arXiv:2505.09388, 2025.
4. Ollama, https://ollama.com and https://github.com/ollama/ollama (accessed October 2026).
5. B. Kandala, "Fully-Offline-AI-agent-using-SLM," GitHub repository, commit ef2d5f5, 2026. https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM
