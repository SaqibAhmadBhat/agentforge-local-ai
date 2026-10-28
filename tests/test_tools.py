"""Unit tests for the tool registry: validation, rejection and result handling."""

from datetime import datetime, timezone

import pytest

from agentforge.errors import ToolValidationError
from agentforge.notes import NoteStore
from agentforge.tools import Parameter, Tool, ToolRegistry, build_default_registry

EXPECTED_TOOLS = [
    "calculator",
    "save_note",
    "read_note",
    "list_notes",
    "search_notes",
    "current_datetime",
    "word_count",
    "get_help",
]


@pytest.fixture
def registry(tmp_path):
    clock = lambda: datetime(2026, 10, 28, 14, 30, 5, tzinfo=timezone.utc)  # noqa: E731
    return build_default_registry(NoteStore(tmp_path / "notes"), max_result_chars=2000, clock=clock)


def test_default_tool_set(registry):
    assert registry.names == EXPECTED_TOOLS


def test_no_code_or_shell_execution_tools_exist(registry):
    dangerous = {"python", "exec", "eval", "shell", "bash", "run_code", "system", "subprocess"}
    assert dangerous.isdisjoint(registry.names)


def test_schemas_are_well_formed(registry):
    for schema in registry.schemas():
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["name"] in EXPECTED_TOOLS and function["description"]
        params = function["parameters"]
        assert params["type"] == "object"
        assert set(params["required"]) <= set(params["properties"])


def test_unknown_tool_is_rejected(registry):
    result = registry.execute("delete_all_files", {})
    assert not result.ok
    assert "Unknown tool 'delete_all_files'" in result.output
    assert "calculator" in result.output  # lists the allowed tools


@pytest.mark.parametrize("name", [None, 42, "", "Calculator", "calculator "])
def test_tool_names_must_match_exactly(registry, name):
    assert not registry.execute(name, {"expression": "1+1"}).ok


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "missing required argument 'expression'"),
        ({"expression": "1+1", "extra": 1}, "unexpected argument"),
        ({"expression": 5}, "must be string, not int"),
        ({"expression": True}, "must be string, not bool"),
        ({"expression": ["1+1"]}, "must be string, not list"),
        ("not json", "must be a JSON object"),
        ("[1, 2]", "must be a JSON object"),
        (["expression"], "must be a JSON object"),
        ({"expression": "1+" * 200}, "too long"),
    ],
)
def test_invalid_arguments_are_rejected(registry, arguments, message):
    with pytest.raises(ToolValidationError, match=message):
        registry.validate("calculator", arguments)
    assert not registry.execute("calculator", arguments).ok


def test_json_string_arguments_are_accepted(registry):
    result = registry.execute("calculator", '{"expression": "6 * 7"}')
    assert result.ok and result.output == "42"


def test_tools_without_parameters_accept_none_or_empty(registry):
    assert registry.execute("list_notes", None).ok
    assert registry.execute("list_notes", {}).ok
    assert not registry.execute("list_notes", {"unexpected": "x"}).ok


def test_expected_tool_failures_become_error_results(registry):
    result = registry.execute("calculator", {"expression": "1/0"})
    assert not result.ok and "Division by zero" in result.output
    result = registry.execute("read_note", {"name": "missing"})
    assert not result.ok and "No note named" in result.output


def test_notes_round_trip_through_tools(registry):
    assert registry.execute("save_note", {"name": "idea", "content": "solar robot"}).ok
    assert registry.execute("list_notes").output == "idea"
    assert registry.execute("read_note", {"name": "idea"}).output == "solar robot"
    assert "idea" in registry.execute("search_notes", {"query": "robot"}).output
    assert "No notes contain" in registry.execute("search_notes", {"query": "zzz"}).output


def test_datetime_word_count_and_help(registry):
    assert registry.execute("current_datetime").output == "Wednesday, 28 October 2026, 14:30:05 (UTC)"
    assert registry.execute("word_count", {"text": "the quick brown fox"}).output == "4 words, 19 characters"
    help_text = registry.execute("get_help").output
    assert "calculator" in help_text and "/run" in help_text


def test_long_results_are_truncated(registry):
    registry.execute("save_note", {"name": "long", "content": "x" * 5000})
    output = registry.execute("read_note", {"name": "long"}).output
    assert len(output) < 2100 and "truncated 3000 characters" in output


def test_help_text_fits_without_truncation(registry):
    assert "truncated" not in registry.execute("get_help").output


def test_unexpected_tool_crash_is_contained():
    def broken(text: str) -> str:
        raise RuntimeError("secret note text should not leak")

    registry = ToolRegistry([Tool("broken", "always fails", broken, (Parameter("text", str, "t"),))])
    result = registry.execute("broken", {"text": "hi"})
    assert not result.ok
    assert result.output == "Internal error in tool 'broken'."


def test_non_string_tool_output_is_rejected():
    registry = ToolRegistry([Tool("bad", "returns int", lambda: 5)])  # type: ignore[arg-type, return-value]
    assert not registry.execute("bad").ok


def test_duplicate_tool_names_are_refused():
    tool = Tool("same", "x", lambda: "x")
    with pytest.raises(ValueError):
        ToolRegistry([tool, tool])
