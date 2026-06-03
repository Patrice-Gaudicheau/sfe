"""Tests for the neutral SFE segment selector."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.segment_selector import (  # noqa: E402
    CandidateSegment,
    ProviderBackedSegmentSelector,
    SegmentSelectionError,
    SegmentSelectionInput,
    build_segment_selection_prompt,
    create_configured_segment_selector,
    parse_segment_selection_output,
)


class SegmentSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selection_input = SegmentSelectionInput(
            request_id="request-1",
            task="Diagnose the payments cache failure.",
            output_contract="Return Cause, Owner, Next action.",
            candidate_segments=(
                CandidateSegment(
                    id="payments-cache",
                    source="Payments cache memo",
                    text="The stale PSP routing cache pay-cache-17 caused failures.",
                    metadata={"fixture_selected": True},
                ),
                CandidateSegment(
                    id="email-provider",
                    source="Email provider memo",
                    text="EchoMail caused receipt delays but not checkout failures.",
                    metadata={"distractor": True},
                ),
            ),
            metadata={"benchmark_type": "output_variation/controlled"},
            model="router-model",
        )

    def test_prompt_includes_schema_task_and_candidate_segments(self) -> None:
        prompt = build_segment_selection_prompt(self.selection_input)

        self.assertIn("Segment selection payload JSON", prompt)
        self.assertIn("Diagnose the payments cache failure.", prompt)
        self.assertIn("payments-cache", prompt)
        self.assertIn("email-provider", prompt)
        self.assertIn("selected_segment_ids", prompt)
        self.assertIn("router_status", prompt)

    def test_parser_accepts_valid_selected_ids_and_candidate_selected_alias(self) -> None:
        parsed = parse_segment_selection_output(
            json.dumps(
                {
                    "router_status": "selected",
                    "router_reason": "payments cache is the relevant subsystem",
                    "selected_segment_ids": ["payments-cache"],
                    "confidence": 0.91,
                }
            ),
            candidate_ids={"payments-cache", "email-provider"},
        )
        alias = parse_segment_selection_output(
            json.dumps(
                {
                    "router_status": "candidate_selected",
                    "router_reason": "selected via legacy field",
                    "candidate_selected_segment_ids": ["email-provider"],
                }
            ),
            candidate_ids={"payments-cache", "email-provider"},
        )

        self.assertEqual(parsed.selected_segment_ids, ("payments-cache",))
        self.assertEqual(parsed.router_status, "selected")
        self.assertEqual(parsed.confidence, 0.91)
        self.assertEqual(alias.selected_segment_ids, ("email-provider",))

    def test_parser_rejects_invalid_json_unknown_ids_and_empty_ids(self) -> None:
        with self.assertRaisesRegex(SegmentSelectionError, "valid JSON"):
            parse_segment_selection_output("not json", candidate_ids={"payments-cache"})
        with self.assertRaisesRegex(SegmentSelectionError, "unknown selected IDs"):
            parse_segment_selection_output(
                '{"selected_segment_ids":["unknown"],"router_reason":"bad id"}',
                candidate_ids={"payments-cache"},
            )
        with self.assertRaisesRegex(SegmentSelectionError, "no selected IDs"):
            parse_segment_selection_output(
                '{"selected_segment_ids":[],"router_reason":"empty"}',
                candidate_ids={"payments-cache"},
            )

    def test_status_is_diagnostic_only_when_selected_ids_are_valid(self) -> None:
        provider = FakeProvider(
            {
                "router_status": "arbitrary_unknown_status",
                "router_reason": "valid ids despite unknown status",
                "selected_segment_ids": ["payments-cache"],
            }
        )
        selector = ProviderBackedSegmentSelector(
            provider=provider,
            provider_name="openai",
            model="router-model",
        )

        result = selector.select(self.selection_input)

        self.assertEqual(result.selected_segment_ids, ("payments-cache",))
        self.assertEqual(result.router_status, "arbitrary_unknown_status")
        self.assertFalse(result.router_status_known)
        self.assertIsNone(result.error_type)
        self.assertTrue(result.selection_usable)

    def test_provider_factory_and_model_env_resolution_for_openai_anthropic_alibaba_google(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_OPENAI_ROUTER_MODEL": "env-openai-router",
                "SFE_ANTHROPIC_ROUTER_MODEL": "env-anthropic-router",
                "SFE_ALIBABA_ROUTER_MODEL": "env-alibaba-router",
                "SFE_GOOGLE_MODEL": "env-google-model",
            },
            clear=True,
        ):
            openai = create_configured_segment_selector(
                provider_name="openai",
                provider_factories={"openai": lambda: FakeProvider()},
            )
            anthropic = create_configured_segment_selector(
                provider_name="anthropic",
                provider_factories={"anthropic": lambda: FakeProvider()},
            )
            alibaba = create_configured_segment_selector(
                provider_name="alibaba",
                provider_factories={"alibaba": lambda: FakeProvider()},
            )
            google = create_configured_segment_selector(
                provider_name="google",
                provider_factories={"google": lambda: FakeProvider()},
            )

        self.assertEqual(openai.provider_name, "openai")
        self.assertEqual(openai.model, "env-openai-router")
        self.assertEqual(anthropic.provider_name, "anthropic")
        self.assertEqual(anthropic.model, "env-anthropic-router")
        self.assertEqual(alibaba.provider_name, "alibaba")
        self.assertEqual(alibaba.model, "env-alibaba-router")
        self.assertEqual(google.provider_name, "google")
        self.assertEqual(google.model, "env-google-model")

    def test_fake_provider_paths_work_without_network_for_each_supported_provider(self) -> None:
        for provider_name in ("openai", "anthropic", "alibaba", "google"):
            with self.subTest(provider_name=provider_name):
                provider = FakeProvider(
                    {
                        "router_status": "selected",
                        "router_reason": f"{provider_name} selected payments cache",
                        "selected_segment_ids": ["payments-cache"],
                    }
                )
                selector = ProviderBackedSegmentSelector(
                    provider=provider,
                    provider_name=provider_name,
                    model=f"{provider_name}-router",
                )

                result = selector.select(self.selection_input)

                self.assertEqual(result.provider_name, provider_name)
                self.assertEqual(result.selected_segment_ids, ("payments-cache",))
                self.assertEqual(result.provider_usage["input_tokens"], 10)
                self.assertEqual(provider.calls[0]["model"], f"{provider_name}-router")
                self.assertIn("neutral SFE segment selector", provider.calls[0]["system_instruction"])

    def test_provider_error_returns_unusable_result(self) -> None:
        selector = ProviderBackedSegmentSelector(
            provider=FailingProvider(),
            provider_name="openai",
            model="router-model",
        )

        result = selector.select(self.selection_input)

        self.assertEqual(result.selected_segment_ids, ())
        self.assertEqual(result.error_type, "RuntimeError")
        self.assertFalse(result.selection_usable)


class FakeProvider:
    def __init__(self, payload: dict[str, object] | None = None) -> None:
        self.payload = payload or {
            "router_status": "selected",
            "router_reason": "default fake selection",
            "selected_segment_ids": ["payments-cache"],
        }
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append({"messages": messages, **kwargs})
        return {
            "choices": [{"message": {"content": json.dumps(self.payload)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }


class FailingProvider:
    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, *_: object, **__: object) -> dict[str, object]:
        raise RuntimeError("provider failed")


if __name__ == "__main__":
    unittest.main()
