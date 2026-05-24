"""Tests for shared configured-router JSON review plumbing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.router_review import (
    DirectProviderJsonReviewer,
    RouterReviewError,
    create_configured_router_json_reviewer,
)


class FakeProvider:
    def __init__(
        self,
        *,
        ok: bool = True,
        content: str | None = None,
    ) -> None:
        self.ok = ok
        self.content = content or json.dumps(
            {
                "decision": "OK_TEST",
                "reason": "review passed",
                "files_reviewed": ["example.py"],
                "risk_level": "low",
            }
        )
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": self.ok}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": self.content}}]}


def _reviewer(provider: FakeProvider) -> DirectProviderJsonReviewer:
    return DirectProviderJsonReviewer(
        provider=provider,
        provider_name="fake-router",
        model="fake-model",
        call_style="system_instruction",
        system_instruction="Return JSON.",
        prompt_builder=lambda payload: json.dumps(payload, sort_keys=True),
        valid_decisions={"OK_TEST", "KO_BLOCK"},
        max_tokens=128,
    )


def test_generic_reviewer_parses_valid_json_decision() -> None:
    decision = _reviewer(FakeProvider()).review({"task": "check"})

    assert decision.decision == "OK_TEST"
    assert decision.reason == "review passed"
    assert decision.files_reviewed == ("example.py",)
    assert decision.risk_level == "low"
    assert decision.provider_name == "fake-router"
    assert decision.model == "fake-model"


def test_generic_reviewer_invalid_json_produces_clear_failure() -> None:
    with pytest.raises(RouterReviewError) as exc_info:
        _reviewer(FakeProvider(content="not json")).review({"task": "check"})

    assert exc_info.value.category == "invalid_router_response"
    assert exc_info.value.reason == "router did not return valid JSON"


def test_generic_reviewer_unsupported_decision_produces_clear_failure() -> None:
    provider = FakeProvider(
        content=json.dumps(
            {
                "decision": "OK_PROMOTE",
                "reason": "wrong schema for this reviewer",
                "files_reviewed": ["example.py"],
                "risk_level": "low",
            }
        )
    )

    with pytest.raises(RouterReviewError) as exc_info:
        _reviewer(provider).review({"task": "check"})

    assert exc_info.value.category == "invalid_router_response"
    assert exc_info.value.reason == "router decision was invalid"


def test_lemonade_router_model_prefers_sfe_router_model() -> None:
    provider = FakeProvider()
    reviewer = create_configured_router_json_reviewer(
        system_instruction="Return JSON.",
        prompt_builder=lambda payload: json.dumps(payload, sort_keys=True),
        valid_decisions={"OK_TEST", "KO_BLOCK"},
        max_tokens=128,
        environ={
            "SFE_PROVIDER": "lemonade",
            "SFE_ROUTER_MODEL": "router-model",
            "SFE_LEMONADE_MODEL": "shared-lemonade-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    decision = reviewer.review({"task": "check"})

    assert decision.provider_name == "lemonade"
    assert decision.model == "router-model"
    assert provider.calls[0]["model"] == "router-model"
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert "system_instruction" not in provider.calls[0]
