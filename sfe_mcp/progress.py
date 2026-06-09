"""MCP progress notification bridge helpers."""

from __future__ import annotations

import asyncio
from asyncio import AbstractEventLoop
from collections.abc import Callable
from typing import Protocol

from sfe.run_pipeline import RunProgressEvent

from .serializers import serialize_progress_event


class ProgressReporter(Protocol):
    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        ...


def create_mcp_progress_callback(
    reporter: ProgressReporter,
    loop: AbstractEventLoop,
) -> Callable[[RunProgressEvent], None]:
    progress_count = 0

    def progress_callback(event: RunProgressEvent) -> None:
        nonlocal progress_count
        progress_count += 1
        message = str(serialize_progress_event(event)["message"])
        future = asyncio.run_coroutine_threadsafe(
            reporter.report_progress(
                float(progress_count),
                None,
                message,
            ),
            loop,
        )
        future.add_done_callback(_consume_progress_notification_result)

    return progress_callback


def _consume_progress_notification_result(future: object) -> None:
    try:
        result = getattr(future, "result")
        result()
    except Exception:
        return
