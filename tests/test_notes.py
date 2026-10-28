"""Unit tests for local note storage."""

import errno
from pathlib import Path

import pytest

from agentforge.notes import MAX_NOTE_CHARS, NoteError, NoteStore, note_key


@pytest.fixture
def store(tmp_path):
    return NoteStore(tmp_path / "notes")


def test_save_then_read(store):
    assert "Saved note 'groceries'" in store.save("groceries", "milk, eggs")
    assert store.read("groceries") == "milk, eggs"


def test_names_are_normalised(store):
    store.save("Shopping List", "bread")
    assert store.read("shopping-list") == "bread"
    assert store.read("shopping_list.txt") == "bread"
    assert store.list_names() == ["shopping-list"]


def test_list_is_sorted_and_empty_at_start(store):
    assert store.list_names() == []
    store.save("b", "2")
    store.save("a", "1")
    assert store.list_names() == ["a", "b"]


def test_existing_note_is_never_overwritten(store):
    store.save("plan", "first")
    with pytest.raises(NoteError, match="already exists"):
        store.save("Plan", "second")
    assert store.read("plan") == "first"


def test_reading_missing_note_fails_clearly(store):
    with pytest.raises(NoteError, match="No note named 'ghost'"):
        store.read("ghost")


def test_search_finds_content_and_names_case_insensitively(store):
    store.save("meeting", "Discuss the ROBOT arm demo on Friday")
    store.save("robot-parts", "servo, battery")
    store.save("other", "nothing relevant")
    hits = store.search("robot")
    assert [h.name for h in hits] == ["meeting", "robot-parts"]
    assert "ROBOT arm" in hits[0].snippet


def test_search_with_no_match_returns_empty(store):
    store.save("a", "alpha")
    assert store.search("zeta") == []


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_invalid_search_query(store, query):
    with pytest.raises(NoteError):
        store.search(query)


@pytest.mark.parametrize("name", ["../../etc/passwd", "/etc/passwd", "..\\..\\secret", "a/b/c"])
def test_path_traversal_is_neutralised(store, tmp_path, name):
    store.save(name, "data")
    saved = list((tmp_path / "notes").iterdir())
    assert len(saved) == 1 and saved[0].parent == tmp_path / "notes"


@pytest.mark.parametrize("name", ["", "   ", "...", "///", "x" * 65])
def test_invalid_names_are_rejected(name):
    with pytest.raises(NoteError):
        note_key(name)


@pytest.mark.parametrize("content", ["", "   ", None, 123])
def test_empty_or_non_text_content_is_rejected(store, content):
    with pytest.raises(NoteError):
        store.save("x", content)


def test_too_large_note_is_rejected(store):
    with pytest.raises(NoteError, match="at most"):
        store.save("big", "a" * (MAX_NOTE_CHARS + 1))


def test_symlink_escape_is_blocked(store, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "link.txt").symlink_to(outside)
    with pytest.raises(NoteError, match="not allowed"):
        store.read("link")


# --- Local data storage failures ------------------------------------------------------


def test_notes_folder_path_is_a_file(tmp_path):
    blocker = tmp_path / "notes"
    blocker.write_text("not a folder")
    with pytest.raises(NoteError, match="Could not create the notes folder"):
        NoteStore(blocker).save("a", "text")


def test_disk_full_while_saving_leaves_no_partial_note(store, tmp_path, monkeypatch):
    real_open = Path.open

    class FailingHandle:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def write(self, text):
            raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "open", lambda self, *a, **k: FailingHandle(real_open(self, *a, **k)))
    with pytest.raises(NoteError, match="Could not save the note: No space left on device"):
        store.save("big", "text")
    monkeypatch.undo()
    assert store.list_names() == []  # the half-written file was removed


def test_permission_denied_on_save_and_read(store, monkeypatch):
    store.save("kept", "text")

    def denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(NoteError, match="Could not save the note: Permission denied"):
        store.save("new", "text")
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(NoteError, match="Could not read the note: Permission denied"):
        store.read("kept")
    with pytest.raises(NoteError, match="Could not search the notes"):
        store.search("text")


def test_storage_failure_reaches_the_model_as_a_tool_error(tmp_path):
    from agentforge.tools import build_default_registry

    blocker = tmp_path / "notes"
    blocker.write_text("not a folder")
    result = build_default_registry(NoteStore(blocker)).execute("save_note", {"name": "a", "content": "b"})
    assert not result.ok and "Could not create the notes folder" in result.output
