"""prompt_toolkit input helpers for the SFE-aware TUI."""

from __future__ import annotations

import sys
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _history_path() -> Path | None:
    try:
        home = Path.home()
        if not home.exists() or not home.is_dir():
            return None
        directory = home / ".sfe"
        directory.mkdir(exist_ok=True)
        return directory / "tui_history"
    except OSError:
        return None


def _history() -> FileHistory | InMemoryHistory:
    path = _history_path()
    if path is None:
        return InMemoryHistory()
    try:
        return FileHistory(str(path))
    except OSError:
        return InMemoryHistory()


def _bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("c-d")
    def submit(event) -> None:
        event.current_buffer.validate_and_handle()

    return bindings


def create_session() -> PromptSession:
    return PromptSession(
        key_bindings=_bindings(),
        history=_history(),
        auto_suggest=AutoSuggestFromHistory(),
        multiline=False,
        enable_history_search=True,
        mouse_support=False,
    )


class TerminalInput:
    """Small input facade so app tests can replace terminal IO."""

    def __init__(self) -> None:
        self._session: PromptSession | None = None

    def prompt(self, message: str, default: str = "") -> str:
        if not is_interactive():
            try:
                value = input()
            except (EOFError, OSError):
                return default
            return value if value else default
        if self._session is None:
            self._session = create_session()
        try:
            value = self._session.prompt(message=message, default=default)
        except EOFError:
            return default
        return value if value is not None else default
