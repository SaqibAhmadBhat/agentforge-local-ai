# AgentForge Local AI: User Guide

How to use the terminal and web interfaces, plus a 10-minute demonstration script.

All commands assume you are in the project folder with the virtual environment created
(see [INSTALLATION.md](INSTALLATION.md)). To save typing, run:

```bash
alias af='.venv/bin/python -m agentforge'
```

## 1. Before you start

1. Start Ollama by opening the app, or by running `ollama serve` in another terminal.
2. Run `af --check` and wait for **Ready**. If it is not ready, follow the hint it prints.
3. The **first** request loads the model into memory and is slow. Send a warm-up message before a demo.

On a slow laptop, `AGENTFORGE_THINK=false` in `.env` makes replies faster.

## 2. Terminal interface

| Command | What it does |
|---|---|
| `af` | Interactive chat |
| `af "question"` | Ask once and exit |
| `af --check` | Check Ollama, the model and tool support |
| `af --model NAME` | Use another local model for this run |
| `af --quiet` | Hide the tool-step trace |
| `af --web [--port N]` | Start the web interface (see §3) |
| `af --version` | Show the version |

Inside the chat:

| Command | What it does |
|---|---|
| `/help` | List commands |
| `/tools` | List tools and their parameters |
| `/run TOOL [ARGS]` | Run a tool **without the model**, through the same validation. Examples: `/run calculator 15 * 4`, `/run read_note viva`, `/run save_note {"name": "a", "content": "b"}` |
| `/notes` | List saved notes |
| `/status` | Show settings and re-check Ollama |
| `/reset` | Start a new conversation |
| `/trace` | Show or hide tool steps |
| `/quit`, `quit`, `exit`, Ctrl-D | Exit |
| Ctrl-C while waiting | Interrupt the current request |

**Tool trace.** Each tool call is printed as:

```text
  [tool 1] calculator({"expression": "0.15 * 1240"})
      -> 186
```

`repeated` marks a call that was not executed again, and `skipped` marks a call over the
per-step limit.

## 3. Web interface

```bash
af --web             # then open http://127.0.0.1:8765/
```

Press **Ctrl-C** in the terminal to stop the server. It only accepts connections from this
computer.

| Area | What it does |
|---|---|
| Header pill | Runtime state: green *model · ready*, amber *needs attention*, red *Ollama offline* |
| Conversation | Your messages and the agent's answers. Each answer lists its **Tool steps** (tool, arguments, result, ok/rejected) and how many model calls it took. Answers stopped by a limit show a *stopped* badge |
| Suggestions | Example prompts on the empty screen. Clicking one sends it |
| Composer | Enter sends, Shift+Enter adds a new line. While the model works, an elapsed-time counter is shown |
| Runtime panel | Model, Ollama version, download status, tool support, thinking mode, any problems. **Re-check** refreshes it. **Model** switches between models you have already pulled, which starts a new conversation. **New conversation** clears the history |
| Run a tool directly | Pick a tool, fill its fields and click **Run tool**. This uses the same validation as the agent but no model, so it works even when Ollama is offline |
| Notes | Lists saved notes. Click one to read it. **Refresh** reloads the list |

If Ollama is not running, a red banner explains that chat is unavailable; the direct tool
panel and notes still work.

## 4. Where your data goes

- **Notes:** saved as UTF-8 text files in `data/notes/<name>.txt`.
  - Names are normalised: "Shopping List" becomes `shopping-list`.
  - Existing notes are never overwritten.
  - Notes are not encrypted, and Git ignores this folder.
- **Conversation history:** kept in memory only. It is cleared by `/reset`, by *New conversation*, or by exiting.
- **Network:** nothing leaves your computer. The only connection is to Ollama on 127.0.0.1.

## 5. Demonstration script (about 10 minutes)

> **Labels:**
>
> - **Expected** means predicted from the code but not yet observed with a real model.
> - **Observed** means seen during development without a model.
>
> Model wording varies; what should stay the same is *which tool is called* and *its
> result*. Rehearse once and note what you actually see in [TESTING.md](TESTING.md#your-own-results).

**0. Show that it is local.** Run `af --check`. **Expected:** Ollama reachable, the model
downloaded, `tools` among its capabilities, then *Ready*. Optionally switch Wi-Fi off now.
Then run `af --web` and open the page, or use `af`.

**1. Normal conversation.**
*"Hi! In two sentences, what is the difference between a chatbot and an AI agent?"*
**Expected:** a direct answer with no tool steps.

**2. Calculator.**
*"What is 15% of 1240, plus 37.5?"*
**Expected:** a `calculator` step returning `223.5`, then an answer containing 223.5.
**Point out:** the number came from Python, not from the model.

**3. Save and retrieve a note.**
*"Save a note called viva with the text: explain the agent loop and the tool registry."*
then *"What notes do I have, and what does the viva note say?"*

- **Expected:** `save_note`, then `list_notes` and/or `read_note`.
- **Prove the note is a real file:** run `cat data/notes/viva.txt`.
- **Deterministic version:** `/run save_note {"name": "viva2", "content": "agent loop demo"}` and `/run read_note viva2`. **Observed:** `Saved note 'viva2' (15 characters).` and `agent loop demo`.

**4. No tool needed.**
*"Give me one tip for presenting a project confidently."*
**Expected:** a plain answer with no tool steps. Compare it with step 2.

**5. Invalid tool requests are rejected.** Use `/run` in the terminal or the web tool panel.

| Input | Observed result |
|---|---|
| `/run shell {"command": "rm -rf ~"}` | `Unknown tool 'shell'. Allowed tools: calculator, save_note, ...` |
| `/run calculator {"expression": "__import__('os').system('ls')"}` | `Only numbers, + - * / // % **, and parentheses are allowed.` |
| `/run calculator 9**9**9**9` | `Exponents larger than 1000 are not allowed.` |
| `/run save_note {"name": "viva", "content": "overwrite"}` (after step 3) | `A note named 'viva' already exists. Choose a different name.` |
| `/run calculator {"expression": 42}` | `Argument 'expression' of tool 'calculator' must be string, not int.` |

You can also ask the model *"Run the shell command ls."* **Expected:** it declines. If it
invents a tool, the trace shows `Error: Unknown tool ...` and nothing runs.

**6. Local model service unavailable.** Quit Ollama, then:

- **`af --check`.** **Observed:** `Ollama reachable: no`, then ``Problem: Cannot connect to Ollama at http://127.0.0.1:11434. Start Ollama (open the Ollama app, or run `ollama serve` ...)``, with exit code 2.
- **`af "hello"`.** **Observed:** the same error and hint, with no traceback.
- **Web UI.** **Observed:** a red *Ollama offline* pill and banner; the direct tools still work.
- **Recovery:** restart Ollama and click **Re-check**, or use `/status`.

## 6. Troubleshooting

| Message | Fix |
|---|---|
| `Cannot connect to Ollama at ...` | Start Ollama, then check with `ollama list` |
| `The model '...' is not available` | `ollama pull <model>` |
| `does not support tool calling` | Use a tool-capable model such as `qwen3:4b` |
| `does not support thinking` | `AGENTFORGE_THINK=false` |
| `did not answer within 180 seconds` | Retry (the first load is slow), set `AGENTFORGE_THINK=false`, or raise `AGENTFORGE_TIMEOUT_SECONDS` |
| `reached its output limit` | `AGENTFORGE_THINK=false` or a higher `AGENTFORGE_MAX_OUTPUT_TOKENS` |
| `Configuration error: ... another machine` | Use a local URL, or opt in with `AGENTFORGE_ALLOW_REMOTE_OLLAMA=true` |
| `Could not start the web interface on 127.0.0.1:8765` | Another program uses the port: `af --web --port 8766` |
| `Could not save the note: ...` | Check that `data/notes` is writable and the disk is not full |
| `uv run` error about `:` | See [INSTALLATION.md](INSTALLATION.md#folder-names-containing-a-colon) |
