"""Core provider progress and idle-supervision primitives."""

from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


PROVIDER_PROGRESS_EVENT_KINDS = frozenset(
    {
        "call_started",
        "request_sent",
        "response_headers",
        "provider_chunk",
        "provider_sse_event",
        "internal_wait",
        "retry_scheduled",
        "call_completed",
        "call_failed",
        "idle_timeout",
    }
)
DEFAULT_PROVIDER_IDLE_TIMEOUT_SECONDS = 300.0
DEFAULT_PROVIDER_INTERNAL_HEARTBEAT_SECONDS = 1.0

ProviderProgressSink = Callable[["ProviderProgressEvent"], None]


@dataclass(frozen=True)
class ProviderProgressEvent:
    """Structured provider progress event emitted by core SFE supervision."""

    call_id: str
    provider: str
    model: str | None
    kind: str
    source: str
    real_provider_signal: bool
    resets_idle_timer: bool
    timestamp_monotonic: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "provider": self.provider,
            "model": self.model,
            "kind": self.kind,
            "source": self.source,
            "real_provider_signal": self.real_provider_signal,
            "resets_idle_timer": self.resets_idle_timer,
            "timestamp_monotonic": self.timestamp_monotonic,
            "metadata": dict(self.metadata),
        }


class ProviderCallIdleTimeoutError(TimeoutError):
    """Raised when no admissible provider progress arrives before the idle window."""

    def __init__(
        self,
        *,
        provider: str,
        model: str | None,
        call_id: str,
        idle_timeout_seconds: float,
    ) -> None:
        self.provider = provider
        self.model = model
        self.call_id = call_id
        self.idle_timeout_seconds = idle_timeout_seconds
        super().__init__(
            "provider call stalled after "
            f"{idle_timeout_seconds:g} seconds without admissible progress"
        )


class ProviderCallSupervisor:
    """Emit provider progress events and enforce idle supervision."""

    def __init__(
        self,
        *,
        provider: str,
        model: str | None = None,
        progress_sink: ProviderProgressSink | None = None,
        call_id: str | None = None,
        idle_timeout_seconds: float | None = None,
        internal_heartbeat_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.model = model
        self.progress_sink = progress_sink
        self.call_id = call_id or uuid.uuid4().hex
        self.idle_timeout_seconds = (
            _resolve_positive_seconds(
                idle_timeout_seconds,
                "SFE_PROVIDER_IDLE_TIMEOUT_SECONDS",
                DEFAULT_PROVIDER_IDLE_TIMEOUT_SECONDS,
            )
        )
        self.internal_heartbeat_seconds = (
            _resolve_positive_seconds(
                internal_heartbeat_seconds,
                "SFE_PROVIDER_INTERNAL_HEARTBEAT_SECONDS",
                DEFAULT_PROVIDER_INTERNAL_HEARTBEAT_SECONDS,
            )
        )
        self.clock = clock
        self._last_admissible_progress_at = self.clock()

    def emit(
        self,
        kind: str,
        *,
        source: str,
        real_provider_signal: bool,
        resets_idle_timer: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderProgressEvent:
        if kind not in PROVIDER_PROGRESS_EVENT_KINDS:
            raise ValueError(f"Unknown provider progress event kind: {kind}")
        if kind == "internal_wait" and real_provider_signal:
            raise ValueError("internal_wait cannot be marked as a real provider signal")
        if resets_idle_timer is None:
            resets_idle_timer = real_provider_signal
        if resets_idle_timer and not real_provider_signal and kind != "call_started":
            raise ValueError("local-only events must not reset provider idle supervision")

        now = self.clock()
        if resets_idle_timer:
            self._last_admissible_progress_at = now
        event = ProviderProgressEvent(
            call_id=self.call_id,
            provider=self.provider,
            model=self.model,
            kind=kind,
            source=source,
            real_provider_signal=real_provider_signal,
            resets_idle_timer=resets_idle_timer,
            timestamp_monotonic=now,
            metadata=dict(metadata or {}),
        )
        if self.progress_sink is not None:
            self.progress_sink(event)
        return event

    def start(self, metadata: dict[str, Any] | None = None) -> ProviderProgressEvent:
        return self.emit(
            "call_started",
            source="sfe_core",
            real_provider_signal=False,
            resets_idle_timer=True,
            metadata=metadata,
        )

    def fail(self, metadata: dict[str, Any] | None = None) -> ProviderProgressEvent:
        return self.emit(
            "call_failed",
            source="sfe_core",
            real_provider_signal=False,
            resets_idle_timer=False,
            metadata=metadata,
        )

    def complete(self, metadata: dict[str, Any] | None = None) -> ProviderProgressEvent:
        return self.emit(
            "call_completed",
            source="sfe_core",
            real_provider_signal=False,
            resets_idle_timer=False,
            metadata=metadata,
        )

    def check_idle(self) -> None:
        if self.clock() - self._last_admissible_progress_at <= self.idle_timeout_seconds:
            return
        self.emit(
            "idle_timeout",
            source="sfe_core",
            real_provider_signal=False,
            resets_idle_timer=False,
            metadata={"idle_timeout_seconds": self.idle_timeout_seconds},
        )
        raise ProviderCallIdleTimeoutError(
            provider=self.provider,
            model=self.model,
            call_id=self.call_id,
            idle_timeout_seconds=self.idle_timeout_seconds,
        )

    def run_blocking(
        self,
        func: Callable[[], Any],
        *,
        wait_metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Run an opaque blocking provider call under idle supervision."""

        results: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def worker() -> None:
            try:
                results.put(("result", func()))
            except BaseException as exc:  # noqa: BLE001
                results.put(("error", exc))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        while True:
            try:
                status, value = results.get(timeout=self.internal_heartbeat_seconds)
            except queue.Empty:
                self.emit(
                    "internal_wait",
                    source="sfe_core",
                    real_provider_signal=False,
                    resets_idle_timer=False,
                    metadata=wait_metadata,
                )
                self.check_idle()
                continue
            if status == "error":
                raise value
            return value


def collect_progress_events() -> tuple[list[ProviderProgressEvent], ProviderProgressSink]:
    events: list[ProviderProgressEvent] = []
    return events, events.append


def event_dicts(events: Iterable[ProviderProgressEvent]) -> list[dict[str, Any]]:
    return [event.to_dict() for event in events]


def _resolve_positive_seconds(
    explicit: float | None,
    env_name: str,
    default: float,
) -> float:
    raw: float | str = explicit if explicit is not None else os.getenv(env_name, default)
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{env_name} must be greater than 0.")
    return value
