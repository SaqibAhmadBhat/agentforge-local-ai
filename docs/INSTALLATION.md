# Installing AgentForge Local AI

This guide covers macOS in detail, with notes for Linux and Windows. Each step says
whether it needs the internet.

## 1. Prerequisites

| Requirement | Check | Get it |
|---|---|---|
| Python 3.10 or newer | `python3 --version` | macOS: [python.org](https://www.python.org/downloads/) or `brew install python` |
| Git | `git --version` | macOS: `xcode-select --install` |
| Ollama 0.9.0 or newer | `ollama --version` | [ollama.com/download](https://ollama.com/download) (needs internet) |
| About 4 GB free RAM and 3 GB free disk for `qwen3:4b` | Activity Monitor | A smaller model can be used, see below |
| *(optional)* `uv` | `uv --version` | [docs.astral.sh/uv](https://docs.astral.sh/uv/) |

## 2. Get the code (internet)

```bash
cd ~/Desktop
git clone https://github.com/SaqibAhmadBhat/agentforge-local-ai.git
cd agentforge-local-ai
```

## 3. Download the model (internet, once)

Start Ollama by opening the Ollama app, or by running `ollama serve` in a separate terminal. Then run:

```bash
ollama pull qwen3:4b      # about 2.5 GB
ollama list               # qwen3:4b should be listed
```

The model weights are stored by Ollama outside this project folder and are never committed
to Git.

## 4. Install AgentForge (internet, once)

**Option A: pip (built into Python)**

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

**Option B: uv** (uses the pinned versions in `uv.lock`)

```bash
uv sync --extra dev
```

**Optional: browser tests for the web interface**

```bash
.venv/bin/pip install playwright
.venv/bin/python -m playwright install chromium
```

## 5. Configure (optional)

```bash
cp .env.example .env
```

Edit `.env` to change the model, timeout or limits. Every setting is explained in
`.env.example` and in the [README](../README.md#configuration). There are no API keys.

## 6. Verify

```bash
.venv/bin/python -m agentforge --version    # AgentForge Local AI 1.0.0
.venv/bin/python -m agentforge --check      # should end with "Ready"
.venv/bin/python -m pytest -q               # automated tests, no model needed
```

`--check` exits with code 0 when everything is ready, 2 when Ollama or the model has a
problem, and 1 for configuration errors. It prints a hint for each problem.

From this point on, AgentForge works **without the internet**.

## Folder names containing a colon

macOS displays a `/` in a Finder folder name (e.g. "AI/ML EWB Project") as `:` in Terminal
(`AI:ML EWB Project`). The `PATH` variable uses `:` as a separator, so inside such a folder:

- `uv run ...` fails with `error: path segment contains separator ':'`;
- `source .venv/bin/activate` does not put `agentforge` on the `PATH`.

Both were observed during verification. **Always calling `.venv/bin/python -m agentforge`
works with any folder name.** Alternatively, rename the folder without `/` (or clone into a
new one, as in step 2); then `uv run agentforge` and `source .venv/bin/activate` work normally.
Always quote paths that contain spaces, e.g. `cd "$HOME/Desktop/AI:ML EWB Project"`.

## Other platforms

- **Linux:** same commands as macOS. Install Ollama with the official instructions at [ollama.com/download](https://ollama.com/download).
- **Windows:** use `py -m venv .venv` and `.venv\Scripts\pip install -e ".[dev]"`, then run `.venv\Scripts\python -m agentforge`. Not tested in this project.
- **Older NVIDIA GPU drivers:** if Ollama fails with `CUDA error: device kernel image is invalid`, set `AGENTFORGE_NUM_GPU=0` to use the CPU.

## Choosing a different model

```bash
ollama pull qwen3:1.7b
.venv/bin/python -m agentforge --model qwen3:1.7b --check
```

- **Tool support:** the model must list `tools` among its capabilities, and `--check` tells you whether it does.
- **Thinking mode:** for models without thinking support (e.g. `llama3.2:3b`), set `AGENTFORGE_THINK=false`.
- **Cloud models:** names ending in `-cloud` run on remote servers, so they are refused.
- **In the web interface:** you can switch between models you have already pulled.

## Updating and uninstalling

```bash
git pull                                   # update the code (internet)
.venv/bin/pip install -e ".[dev]"          # refresh dependencies if pyproject.toml changed

rm -rf .venv                               # remove the virtual environment
rm -rf data                                # delete your notes (cannot be undone)
ollama rm qwen3:4b                         # remove the model from Ollama
```
