"""Core provider progress and idle-supervision primitives."""

from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping


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
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.call_id = call_id
        self.idle_timeout_seconds = idle_timeout_seconds
        self.diagnostics = dict(diagnostics or {})
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
        role: str | None = None,
        progress_sink: ProviderProgressSink | None = None,
        call_id: str | None = None,
        idle_timeout_seconds: float | None = None,
        internal_heartbeat_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.provider = provider
        self.model = model
        self.role = _clean_label(role)
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
        self._started_at = self.clock()
        self._last_admissible_progress_at = self._started_at
        self._provider_output_seen = False
        self._provider_stdout_chunk_count = 0
        self._last_provider_event_kind: str | None = None
        self._last_provider_event_at: float | None = None

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
        if real_provider_signal:
            self._provider_output_seen = True
            self._last_provider_event_kind = kind
            self._last_provider_event_at = now
            if kind == "provider_chunk":
                self._provider_stdout_chunk_count += 1
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
            diagnostics=self.timeout_diagnostics(timeout_kind="idle"),
        )

    def timeout_diagnostics(self, *, timeout_kind: str) -> dict[str, Any]:
        now = self.clock()
        last_provider_event_elapsed = None
        if self._last_provider_event_at is not None:
            last_provider_event_elapsed = self._last_provider_event_at - self._started_at
        return {
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "call_id": self.call_id,
            "timeout_kind": timeout_kind,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "elapsed_seconds": now - self._started_at,
            "provider_output_seen": self._provider_output_seen,
            "provider_stdout_chunk_count": self._provider_stdout_chunk_count,
            "last_provider_event_kind": self._last_provider_event_kind,
            "last_provider_event_elapsed_seconds": last_provider_event_elapsed,
        }

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


def resolve_provider_idle_timeout_seconds(
    *,
    role: str | None = None,
    provider_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    default: float = DEFAULT_PROVIDER_IDLE_TIMEOUT_SECONDS,
) -> float:
    """Resolve provider idle timeout using provider/role-specific fallbacks."""

    env = os.environ if environ is None else environ
    env_names: list[str] = []
    normalized_role = _env_label(role)
    normalized_provider = _env_label(provider_name)
    if normalized_provider is not None and normalized_role is not None:
        env_names.append(
            f"SFE_{normalized_provider}_{normalized_role}_IDLE_TIMEOUT_SECONDS"
        )
    if normalized_role is not None:
        env_names.append(f"SFE_PROVIDER_{normalized_role}_IDLE_TIMEOUT_SECONDS")
    env_names.append("SFE_PROVIDER_IDLE_TIMEOUT_SECONDS")
    for env_name in env_names:
        raw = env.get(env_name)
        if raw is None or raw.strip() == "":
            continue
        return _positive_seconds(raw, env_name)
    return _positive_seconds(default, "SFE_PROVIDER_IDLE_TIMEOUT_SECONDS")


def _resolve_positive_seconds(
    explicit: float | None,
    env_name: str,
    default: float,
) -> float:
    raw: float | str = explicit if explicit is not None else os.getenv(env_name, default)
    return _positive_seconds(raw, env_name)


def _positive_seconds(raw: float | str, env_name: str) -> float:
    value = float(raw)
    if value <= 0:
        raise ValueError(f"{env_name} must be greater than 0.")
    return value


def _env_label(value: str | None) -> str | None:
    cleaned = _clean_label(value)
    if cleaned is None:
        return None
    return "".join(char if char.isalnum() else "_" for char in cleaned.upper())


def _clean_label(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()
