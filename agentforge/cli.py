"""AgentForge's terminal interface.

Usage:
    agentforge                      interactive chat
    agentforge "what is 15% of 1240?"   ask one question and exit
    agentforge --check              check Ollama and the model, then exit
    agentforge --web                local web interface at http://127.0.0.1:8765/

(`python -m agentforge ...` works the same way.)

Exit codes: 0 success, 1 configuration/input error, 2 model service problem.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from typing import TextIO

from agentforge import APP_FULL_NAME, APP_NAME, TAGLINE, __version__
from agentforge.agent import STOP_FINAL_ANSWER, Agent, AgentStep
from agentforge.config import Settings, load_settings, validate_model
from agentforge.errors import AgentForgeError, ConfigError, InputError, LLMError
from agentforge.llm import OllamaBackend, ServiceStatus
from agentforge.notes import NoteStore
from agentforge.tools import CLI_COMMANDS_HELP, ToolRegistry, build_default_registry

EXIT_OK, EXIT_USAGE, EXIT_SERVICE = 0, 1, 2


class Style:
    """Minimal ANSI colours, disabled when output is not a terminal or NO_COLOR is set."""

    def __init__(self, stream: TextIO) -> None:
        self.enabled = stream.isatty() and "NO_COLOR" not in os.environ

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def title(self, text: str) -> str:
        return self._wrap("1;36", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def good(self, text: str) -> str:
        return self._wrap("32", text)

    def bad(self, text: str) -> str:
        return self._wrap("31", text)

    def accent(self, text: str) -> str:
        return self._wrap("1;35", text)


class AgentForgeCLI:
    """Wires settings, model backend, tools and agent together for the CLI."""

    def __init__(self, settings: Settings, out: TextIO = sys.stdout, show_trace: bool = True) -> None:
        self.settings = settings
        self.out = out
        self.style = Style(out)
        self.show_trace = show_trace
        self.notes = NoteStore(settings.notes_dir)
        self.registry: ToolRegistry = build_default_registry(self.notes, settings.max_tool_result_chars)
        self.backend = OllamaBackend(settings)
        self.agent = Agent(self.backend, self.registry, settings, on_step=self._print_step)

    # -- output helpers -----------------------------------------------------------------

    def say(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def error(self, exc: AgentForgeError) -> None:
        self.say(self.style.bad(f"Error: {exc}"))
        if exc.hint:
            self.say(f"Hint: {exc.hint}")

    def _print_step(self, step: AgentStep) -> None:
        if not self.show_trace:
            return
        arguments = json.dumps(step.arguments, ensure_ascii=False) if step.arguments is not None else "{}"
        marker = "repeated" if step.repeated else "skipped" if step.skipped else "tool"
        self.say(self.style.dim(f"  [{marker} {step.iteration}] {step.tool}({arguments})"))
        result = step.output if len(step.output) <= 300 else step.output[:300] + "..."
        self.say((self.style.dim if step.ok else self.style.bad)(f"      -> {result}"))

    def banner(self) -> None:
        s = self.settings
        self.say(self.style.title(f"{APP_FULL_NAME} v{__version__}") + self.style.dim(f"  {TAGLINE}"))
        self.say(
            self.style.dim(
                f"Model {s.model} via Ollama at {s.ollama_url} - no cloud APIs, notes stay on this computer."
            )
        )
        self.say(self.style.dim("Type a message, /help for commands, /quit to exit."))

    def print_status(self, status: ServiceStatus) -> None:
        s = self.settings
        self.say(f"Model:            {s.model}")
        self.say(f"Ollama URL:       {s.ollama_url}")
        self.say(f"Ollama reachable: {'yes, version ' + str(status.server_version) if status.reachable else 'no'}")
        self.say(f"Model downloaded: {'yes' if status.model_available else 'no / unknown'}")
        if status.capabilities is not None:
            self.say(f"Capabilities:     {', '.join(status.capabilities)}")
        self.say(f"Thinking mode:    {'on' if s.think else 'off'}")
        self.say(f"Max iterations:   {s.max_iterations}   Timeout: {s.request_timeout:g}s")
        self.say(f"Notes folder:     {s.notes_dir}")
        for warning in status.warnings:
            self.say(self.style.accent(warning))
        if status.ok:
            self.say(self.style.good("Ready: the local model service looks good."))
        else:
            for problem in status.problems:
                self.say(self.style.bad(f"Problem: {problem}"))

    # -- actions ------------------------------------------------------------------------

    def ask(self, text: str) -> int:
        """Send one request to the agent and print the answer. Returns an exit code."""
        try:
            result = self.agent.run(text)
        except InputError as exc:
            self.error(exc)
            return EXIT_USAGE
        except LLMError as exc:
            self.error(exc)
            self.say(self.style.dim("Tools still work without the model, e.g. /run calculator 2+2 or /notes."))
            return EXIT_SERVICE
        label = (
            self.style.accent(f"{APP_NAME}:")
            if result.stop_reason == STOP_FINAL_ANSWER
            else self.style.bad(f"{APP_NAME} (stopped):")
        )
        self.say(f"\n{label} {result.answer}\n")
        return EXIT_OK

    def run_tool_command(self, argument_text: str) -> None:
        """Handle `/run TOOL [ARGS]`: call a tool directly through the same validation as the agent."""
        name, _, rest = argument_text.strip().partition(" ")
        if not name:
            self.say("Usage: /run TOOL [ARGS]   e.g. /run calculator 2 + 2")
            return
        rest = rest.strip()
        tool = self.registry.get(name)
        if rest.startswith("{"):
            arguments: object = rest  # JSON text; the registry decodes and validates it
        elif rest and tool is not None and len(tool.parameters) == 1:
            arguments = {tool.parameters[0].name: rest}  # shortcut for one-argument tools
        elif rest:
            arguments = rest  # not JSON: the registry will reject it with a clear message
        else:
            arguments = {}
        result = self.registry.execute(name, arguments)
        if result.ok:
            self.say(self.style.good(f"[{name}] ") + result.output)
        else:
            self.say(self.style.bad(f"Rejected/failed: {result.output}"))

    def handle_command(self, line: str) -> bool:
        """Handle a /command. Returns False when the user wants to quit."""
        command, _, argument = line.partition(" ")
        command = command.lower()
        if command in {"/quit", "/exit", "/q"}:
            return False
        if command in {"/help", "/?"}:
            self.say(CLI_COMMANDS_HELP)
        elif command == "/tools":
            for tool in self.registry.tools:
                params = ", ".join(p.name for p in tool.parameters)
                self.say(f"  {tool.name}({params}) - {tool.description}")
        elif command == "/run":
            self.run_tool_command(argument)
        elif command == "/notes":
            self.run_tool_command("list_notes")
        elif command == "/status":
            self.print_status(self.backend.check())
        elif command == "/reset":
            self.agent.reset()
            self.say("Conversation cleared.")
        elif command == "/trace":
            self.show_trace = not self.show_trace
            self.say(f"Tool trace {'on' if self.show_trace else 'off'}.")
        else:
            self.say(f"Unknown command {command}. Type /help.")
        return True

    def repl(self, read_line: Callable[[str], str] = input) -> int:
        """Interactive loop."""
        self.banner()
        status = self.backend.check()
        if status.ok:
            self.say(
                self.style.good(f"Connected to Ollama {status.server_version}; model {self.settings.model} is ready.\n")
            )
        else:
            for problem in status.problems:
                self.say(self.style.bad(f"Problem: {problem}"))
            self.say(self.style.dim("Chat needs the model, but /run, /notes and /help still work.\n"))
        while True:
            try:
                line = read_line("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                self.say("\nBye.")
                return EXIT_OK
            if not line:
                continue
            if line.lower() in {"quit", "exit"}:
                self.say("Bye.")
                return EXIT_OK
            if line.startswith("/"):
                if not self.handle_command(line):
                    self.say("Bye.")
                    return EXIT_OK
                continue
            try:
                self.ask(line)
            except KeyboardInterrupt:
                self.say("\nInterrupted.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentforge", description=f"{APP_FULL_NAME}: {TAGLINE}")
    parser.add_argument("task", nargs="*", help="ask one question and exit (omit for interactive chat)")
    parser.add_argument("--check", action="store_true", help="check Ollama and the model, then exit")
    parser.add_argument("--web", action="store_true", help="start the local web interface (127.0.0.1 only)")
    parser.add_argument("--port", type=int, help="port for --web (default 8765 or AGENTFORGE_WEB_PORT)")
    parser.add_argument("--model", help="override AGENTFORGE_MODEL for this run")
    parser.add_argument("--quiet", action="store_true", help="hide the tool-call trace")
    parser.add_argument("--debug", action="store_true", help="show debug logs (never includes note text)")
    parser.add_argument("--version", action="version", version=f"{APP_FULL_NAME} {__version__}")
    return parser


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    """Entry point for the `agentforge` command."""
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )

    try:
        settings = load_settings()
        if args.model:
            settings = replace(settings, model=validate_model(args.model))
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=out)
        if exc.hint:
            print(f"Hint: {exc.hint}", file=out)
        return EXIT_USAGE

    if args.web:
        from agentforge.web import serve  # imported lazily: only needed for --web

        return serve(settings, port=args.port, out=out)

    app = AgentForgeCLI(settings, out=out, show_trace=not args.quiet)
    if args.check:
        status = app.backend.check()
        app.print_status(status)
        return EXIT_OK if status.ok else EXIT_SERVICE
    if args.task:
        return app.ask(" ".join(args.task))
    return app.repl()


if __name__ == "__main__":
    raise SystemExit(main())
