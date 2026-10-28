# Third-Party Notices

AgentForge Local AI includes and depends on third-party work. This file records that work, its
licences, and what this repository redistributes.

## 1. Upstream project (code included and modified)

**Fully-Offline-AI-agent-using-SLM** (published as `offline-slm-agent`)

- **Source:** https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM
- **Version used:** commit [`ef2d5f5`](https://github.com/BhargavaKandala/Fully-Offline-AI-agent-using-SLM/tree/ef2d5f5) (2026-07-27)
- **Licence:** MIT
- **Copyright:** © 2026 Bhargava Kandala

AgentForge Local AI is a modified and extended version of this work. The upstream commits are authored as "Kandala Naga Venkata Surya Sree Bhargava" (GitHub: BhargavaKandala). As the MIT licence requires,
the copyright notice and permission notice are kept in [`LICENSE`](../LICENSE). The full text
is reproduced below:

```text
MIT License

Copyright (c) 2026 Bhargava Kandala

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

The upstream README credits a tutorial by
[@datasciencebrain](https://www.instagram.com/datasciencebrain/) as the original concept.
The licence does not require this credit; it is kept as a courtesy.

## 2. Python dependencies (installed by the user, not redistributed)

These packages are downloaded by `pip` or `uv` at install time. They are not copied into
this repository. Licences are as declared in each package's metadata for the versions
tested:

| Package | Version tested | Licence | Why it is needed |
|---|---|---|---|
| ollama | 0.6.2, 0.6.3 | MIT | Official Ollama client (direct) |
| httpx | 0.28.1 | BSD-3-Clause | HTTP client used by `ollama` and by the health check (direct) |
| python-dotenv | 1.2.4 | BSD-3-Clause | Reads the `.env` file (direct) |
| pydantic, pydantic-core | 2.x | MIT | Used by `ollama` (transitive) |
| httpcore | 1.0.x | BSD-3-Clause | Used by httpx (transitive) |
| anyio | 4.x | MIT | Used by httpx (transitive) |
| h11 | 0.16.x | MIT | Used by httpcore (transitive) |
| idna | 3.x | BSD-3-Clause | Used by httpx (transitive) |
| certifi | 2026.x | MPL-2.0 | CA certificates used by httpx (transitive, unmodified) |
| typing-extensions | 4.x | PSF-2.0 | Transitive |
| annotated-types, typing-inspection | 0.x | MIT | Used by pydantic (transitive) |
| pytest (development only) | 9.2.0 | MIT | Test runner |
| playwright (optional, browser tests only) | 1.63 | Apache-2.0 | Drives headless Chromium in `tests/test_ui_browser.py`; not installed by default |
| iniconfig, pluggy, exceptiongroup, tomli (development only) | – | MIT | Used by pytest |
| packaging (development only) | – | Apache-2.0 OR BSD-2-Clause | Used by pytest |
| Pygments (development only) | – | BSD-2-Clause | Used by pytest |
| colorama (development only, Windows) | – | BSD-3-Clause | Used by pytest |

The exact resolved versions are pinned in `uv.lock`.

## 3. Front-end assets

The web interface uses no third-party front-end code, fonts, icons or CDN resources. All
HTML, CSS, JavaScript and the SVG logo in `agentforge/static/` were written for this project.
The text uses the operating system's own fonts.

## 4. External software and models (not included)

| Item | Licence | Notes |
|---|---|---|
| [Ollama](https://github.com/ollama/ollama) | MIT | Separate program that the user installs. AgentForge talks to it over HTTP on 127.0.0.1 |
| Qwen3-4B model weights (`qwen3:4b` in Ollama) | Apache-2.0 (per the [Qwen/Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B)) | Downloaded by the user with `ollama pull`. Not part of this repository. If you use a different model, check that model's licence |

## 5. AgentForge Local AI modifications

The modifications and new files in this repository, including the AgentForge name, logo
(`agentforge/static/logo.svg`), documentation, screenshots and presentation, are
© 2026 Saqib Ahmad Bhat and are released under the same MIT licence (see [`LICENSE`](../LICENSE)).
