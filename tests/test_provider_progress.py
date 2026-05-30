from __future__ import annotations

import time
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.provider_progress import (
    ProviderCallIdleTimeoutError,
    ProviderCallSupervisor,
    collect_progress_events,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_provider_progress_event_order_and_completion() -> None:
    events, sink = collect_progress_events()
    clock = FakeClock()
    supervisor = ProviderCallSupervisor(
        provider="fake",
        model="fake-model",
        progress_sink=sink,
        idle_timeout_seconds=5,
        clock=clock,
    )

    supervisor.start()
    supervisor.emit("request_sent", source="test", real_provider_signal=False)
    supervisor.emit("response_headers", source="test", real_provider_signal=True)
    supervisor.complete()

    assert [event.kind for event in events] == [
        "call_started",
        "request_sent",
        "response_headers",
        "call_completed",
    ]
    assert events[2].real_provider_signal is True
    assert events[2].resets_idle_timer is True


def test_internal_wait_is_never_a_real_provider_signal() -> None:
    events, sink = collect_progress_events()
    supervisor = ProviderCallSupervisor(
        provider="fake",
        progress_sink=sink,
        idle_timeout_seconds=5,
    )

    supervisor.emit(
        "internal_wait",
        source="sfe_core",
        real_provider_signal=False,
        resets_idle_timer=False,
    )

    assert events[0].kind == "internal_wait"
    assert events[0].real_provider_signal is False
    assert events[0].resets_idle_timer is False

    with pytest.raises(ValueError):
        supervisor.emit(
            "internal_wait",
            source="sfe_core",
            real_provider_signal=True,
        )


def test_real_provider_progress_resets_idle_supervision() -> None:
    events, sink = collect_progress_events()
    clock = FakeClock()
    supervisor = ProviderCallSupervisor(
        provider="fake",
        progress_sink=sink,
        idle_timeout_seconds=10,
        clock=clock,
    )

    supervisor.start()
    clock.advance(9)
    supervisor.emit("provider_chunk", source="test", real_provider_signal=True)
    clock.advance(9)
    supervisor.check_idle()
    clock.advance(2)

    with pytest.raises(ProviderCallIdleTimeoutError):
        supervisor.check_idle()

    assert events[-1].kind == "idle_timeout"


def test_run_blocking_emits_internal_wait_then_stalls() -> None:
    events, sink = collect_progress_events()
    supervisor = ProviderCallSupervisor(
        provider="fake",
        progress_sink=sink,
        idle_timeout_seconds=0.02,
        internal_heartbeat_seconds=0.01,
    )
    supervisor.start()

    with pytest.raises(ProviderCallIdleTimeoutError):
        supervisor.run_blocking(lambda: time.sleep(0.1))

    kinds = [event.kind for event in events]
    assert "internal_wait" in kinds
    assert kinds[-1] == "idle_timeout"
    assert all(
        event.real_provider_signal is False
        for event in events
        if event.kind == "internal_wait"
    )


def test_completed_blocking_call_does_not_false_timeout() -> None:
    events, sink = collect_progress_events()
    supervisor = ProviderCallSupervisor(
        provider="fake",
        progress_sink=sink,
        idle_timeout_seconds=1,
        internal_heartbeat_seconds=0.01,
    )
    supervisor.start()

    assert supervisor.run_blocking(lambda: "ok") == "ok"
    supervisor.complete()

    assert events[-1].kind == "call_completed"
    assert "idle_timeout" not in [event.kind for event in events]
