"""Local note storage: one UTF-8 text file per note inside a single folder.

Note names are converted to safe file names ("Shopping List" -> shopping-list.txt),
so a name can never point outside the notes folder. Notes never leave this computer.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass
from pathlib import Path

from agentforge.errors import ToolExecutionError

MAX_NAME_LENGTH = 64
MAX_NOTE_CHARS = 10_000
MAX_QUERY_LENGTH = 200
MAX_SEARCH_RESULTS = 10
NOTE_SUFFIX = ".txt"


class NoteError(ToolExecutionError):
    """A note operation failed (invalid name, missing note, duplicate, too large...)."""


@dataclass(frozen=True)
class SearchHit:
    """One search result: the note name and a short snippet around the match."""

    name: str
    snippet: str


def note_key(name: str) -> str:
    """Normalise a note name into a safe file stem: lowercase letters, digits and hyphens.

    'Shopping List', 'shopping-list' and 'shopping_list.txt' all map to 'shopping-list'.
    """
    if not isinstance(name, str):
        raise NoteError("The note name must be text.")
    stem = name.strip()
    if len(stem) > MAX_NAME_LENGTH:
        raise NoteError(f"Note names can be at most {MAX_NAME_LENGTH} characters.")
    for suffix in (".txt", ".md"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    key = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    if not key:
        raise NoteError("The note name must contain at least one letter or digit.")
    return key


class NoteStore:
    """Save, read, list and search notes in one folder."""

    def __init__(self, notes_dir: Path) -> None:
        self.notes_dir = Path(notes_dir)

    def _path_for(self, name: str) -> Path:
        path = (self.notes_dir / f"{note_key(name)}{NOTE_SUFFIX}").resolve()
        # Defence in depth: note_key() already removes path separators, but also make
        # sure a symlink inside the folder cannot redirect us somewhere else.
        if not path.is_relative_to(self.notes_dir.resolve()):
            raise NoteError("That note name is not allowed.")
        return path

    def save(self, name: str, content: str) -> str:
        """Create a new note. Existing notes are never overwritten."""
        if not isinstance(content, str) or not content.strip():
            raise NoteError("The note content must be non-empty text.")
        if len(content) > MAX_NOTE_CHARS:
            raise NoteError(f"Notes can be at most {MAX_NOTE_CHARS} characters.")
        try:
            self.notes_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise self._storage_error("create the notes folder", exc) from None
        path = self._path_for(name)
        try:
            # Mode "x" fails if the file exists, so a note is never silently replaced.
            with path.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            raise NoteError(f"A note named '{path.stem}' already exists. Choose a different name.") from None
        except OSError as exc:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)  # never leave a half-written note behind
            raise self._storage_error("save the note", exc) from None
        return f"Saved note '{path.stem}' ({len(content)} characters)."

    def read(self, name: str) -> str:
        """Return the text of an existing note."""
        path = self._path_for(name)
        if not path.is_file():
            raise NoteError(f"No note named '{path.stem}' exists. Use list_notes to see saved notes.")
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise self._storage_error("read the note", exc) from None

    def list_names(self) -> list[str]:
        """Return the names of all notes, sorted alphabetically."""
        if not self.notes_dir.is_dir():
            return []
        try:
            return sorted(p.stem for p in self.notes_dir.glob(f"*{NOTE_SUFFIX}") if p.is_file())
        except OSError as exc:
            raise self._storage_error("list the notes", exc) from None

    def search(self, query: str) -> list[SearchHit]:
        """Case-insensitive search of note names and contents."""
        if not isinstance(query, str) or not query.strip():
            raise NoteError("The search text must not be empty.")
        if len(query) > MAX_QUERY_LENGTH:
            raise NoteError(f"The search text can be at most {MAX_QUERY_LENGTH} characters.")
        needle = query.strip().lower()
        name_needle = re.sub(r"[^a-z0-9]+", "-", needle).strip("-")  # same form as note names
        hits: list[SearchHit] = []
        for name in self.list_names():
            try:
                text = (self.notes_dir / f"{name}{NOTE_SUFFIX}").read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise self._storage_error("search the notes", exc) from None
            position = text.lower().find(needle)
            if position >= 0:
                hits.append(SearchHit(name, _snippet(text, position, len(needle))))
            elif name_needle and name_needle in name:
                hits.append(SearchHit(name, _snippet(text, 0, 0)))
            if len(hits) >= MAX_SEARCH_RESULTS:
                break
        return hits

    def _storage_error(self, action: str, exc: OSError) -> NoteError:
        """A clear message for disk problems (permissions, full disk, missing folder)."""
        reason = exc.strerror or type(exc).__name__
        return NoteError(f"Could not {action}: {reason}. Check that {self.notes_dir} exists and is writable.")


def _snippet(text: str, position: int, length: int, context: int = 40) -> str:
    start = max(0, position - context)
    end = min(len(text), position + length + context)
    snippet = " ".join(text[start:end].split())
    return ("..." if start > 0 else "") + snippet + ("..." if end < len(text) else "")
