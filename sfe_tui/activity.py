"""Minimal terminal activity indicators for long-running TUI commands."""

from __future__ import annotations

import os
import sys
import threading
from typing import Protocol, TextIO

from .input import is_interactive


class ActivityIndicator(Protocol):
    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...


def activity_enabled_from_env(environ: dict[str, str] | None = None) -> bool | None:
    value = (environ or os.environ).get("SFE_TUI_ACTIVITY")
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return None


class TerminalActivityIndicator:
    """Render a small same-line spinner while a blocking TUI action runs."""

    def __init__(
        self,
        *,
        message: str = "SFE is working",
        frames: tuple[str, ...] = ("|", "/", "-", "\\"),
        interval_seconds: float = 0.12,
        enabled: bool | None = None,
        stream: TextIO | None = None,
    ) -> None:
        self.message = message
        self.frames = frames
        self.interval_seconds = interval_seconds
        self.stream = stream or sys.stdout
        env_enabled = activity_enabled_from_env()
        self.enabled = (
            env_enabled
            if enabled is None and env_enabled is not None
            else enabled
            if enabled is not None
            else is_interactive()
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_width = 0

    def start(self) -> None:
        if not self.enabled or not self.frames:
            return
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=max(self.interval_seconds * 2, 0.2))
        self._thread = None
        self._clear_line()

    def _run(self) -> None:
        frame_index = 0
        while not self._stop_event.is_set():
            frame = self.frames[frame_index % len(self.frames)]
            self._write_frame(frame)
            frame_index += 1
            self._stop_event.wait(self.interval_seconds)

    def _write_frame(self, frame: str) -> None:
        line = f"{self.message} {frame}"
        self._last_width = max(self._last_width, len(line))
        try:
            self.stream.write("\r" + line)
            self.stream.flush()
        except OSError:
            self._stop_event.set()

    def _clear_line(self) -> None:
        if self._last_width <= 0:
            return
        try:
            self.stream.write("\r" + (" " * self._last_width) + "\r")
            self.stream.flush()
        except OSError:
            return
