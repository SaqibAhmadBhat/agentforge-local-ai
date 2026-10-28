"""Browser tests for the web interface (optional).

These drive the real page in headless Chromium through Playwright, with a scripted fake
model. They are skipped automatically when the optional `playwright` package or its
browser is not installed:

    pip install playwright && python -m playwright install chromium
"""

import threading

import pytest
from helpers import reply
from test_web import FakeRuntime

from agentforge.web import WebApp, create_server

playwright_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.ui


@pytest.fixture
def page_and_backend(settings):
    backend = FakeRuntime()
    server = create_server(WebApp(settings, backend_factory=lambda s: backend), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    with playwright_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - browser binary missing
            pytest.skip(f"Chromium not available: {exc}")
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
        page.goto(url)
        yield page, backend, errors
        browser.close()
    server.shutdown()
    server.server_close()


def test_page_loads_with_runtime_status_and_no_errors(page_and_backend):
    page, _, errors = page_and_backend
    playwright_api.expect(page.locator("#runtime-text")).to_have_text("qwen3:4b · ready")
    playwright_api.expect(page.locator("#empty-state")).to_be_visible()
    playwright_api.expect(page.locator("#model-select option")).to_have_count(2)
    assert errors == []


def test_chat_shows_answer_and_tool_steps(page_and_backend):
    page, backend, errors = page_and_backend
    backend.script += [reply("", ("calculator", {"expression": "0.15 * 1240 + 37.5"})), reply("The result is 223.5.")]
    page.fill("#input", "What is 15% of 1240, plus 37.5?")
    page.keyboard.press("Enter")
    assistant = page.locator(".msg.assistant").last
    playwright_api.expect(assistant).to_contain_text("The result is 223.5.")
    playwright_api.expect(assistant.locator(".step")).to_contain_text("calculator")
    playwright_api.expect(assistant.locator(".step")).to_contain_text("223.5")
    playwright_api.expect(page.locator("#empty-state")).to_be_hidden()
    assert errors == []


def test_model_output_is_shown_as_text_not_html(page_and_backend):
    page, backend, _ = page_and_backend
    backend.script.append(reply("<img src=x onerror=\"document.title='pwned'\">"))
    page.fill("#input", "say something odd")
    page.click("#send")
    playwright_api.expect(page.locator(".msg.assistant").last).to_contain_text("<img src=x")
    assert page.title() == "AgentForge Local AI"


def test_direct_tool_panel_and_notes(page_and_backend):
    page, backend, _ = page_and_backend
    page.select_option("#tool-select", "save_note")
    page.fill("[data-param=name]", "viva")
    page.fill("[data-param=content]", "explain the agent loop")
    page.click("#tool-run")
    playwright_api.expect(page.locator("#tool-output")).to_contain_text("Saved note 'viva'")
    playwright_api.expect(page.locator("#notes-list")).to_contain_text("viva")
    page.click("#notes-list button")
    playwright_api.expect(page.locator("#note-view")).to_contain_text("explain the agent loop")
    page.select_option("#tool-select", "calculator")
    page.fill("[data-param=expression]", "1/0")
    page.click("#tool-run")
    playwright_api.expect(page.locator("#tool-output")).to_contain_text("Division by zero")
    assert backend.requests == []


def test_new_conversation_and_suggestion_chip(page_and_backend):
    page, backend, _ = page_and_backend
    backend.script.append(reply("I can calculate, keep notes and tell the time."))
    page.click("text=What can you do?")
    playwright_api.expect(page.locator(".msg.assistant").last).to_contain_text("I can calculate")
    page.click("#reset")
    playwright_api.expect(page.locator("#empty-state")).to_be_visible()
    playwright_api.expect(page.locator(".msg")).to_have_count(0)
