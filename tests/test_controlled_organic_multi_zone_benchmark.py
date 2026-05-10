"""Tests for the deterministic controlled organic multi-zone benchmark."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_controlled_organic_multi_zone_benchmark import (
    BENCHMARK_TYPE,
    FixtureOrganicExecutor,
    FixtureOrganicSelector,
    OpenAIOrganicSelectorSmoke,
    _build_executor_from_args,
    _build_selector_from_args,
    _parse_args,
    build_openai_selector_prompt,
    build_selection,
    execute_task,
    get_controlled_organic_tasks,
    run_benchmark,
    source_by_id,
    validate_output,
    validate_selection,
    write_markdown,
)


def _selector_json(selected_source_ids: list[str], roles: dict[str, str] | None = None) -> str:
    role_map = roles or {
        "doc-release-notes-helix-2026-11": "release_notes",
        "doc-policy-thresholds-current": "policy_thresholds",
        "doc-service-ownership-map": "ownership_map",
        "doc-incident-followup-778": "evidence_record",
        "doc-policy-thresholds-previous": "previous_policy",
        "doc-ops-note-local-override": "ops_note",
        "doc-release-notes-draft": "draft_release_notes",
    }
    selected_roles = {
        source_id: role_map.get(source_id, "unknown") for source_id in selected_source_ids
    }
    return (
        "{"
        f'"selected_source_ids": {selected_source_ids!r}, '
        f'"source_roles": {selected_roles!r}, '
        '"confidence": 0.93, '
        '"evidence_rationale": "Selected the complete controlled organic source set.", '
        '"fallback_used": false'
        "}"
    ).replace("'", '"')


class FakeOpenAISelectorProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_instruction": system_instruction,
            }
        )
        return {
            "choices": [{"message": {"content": self.content}}],
            "usage": {
                "prompt_tokens": 600,
                "completion_tokens": 120,
                "total_tokens": 720,
            },
        }


class FailingSelector:
    provider = "deterministic_test"
    selector_mode = "failing_selector"
    model: str | None = None
    api_path: str | None = None

    def select(self, task: Any, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("selector failed")


class ControlledOrganicBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_controlled_organic_tasks()
        self.task = self.tasks[0]
        self.fixture_selection = FixtureOrganicSelector().select(self.task, {})

    def _selection_without(self, omitted_source_id: str) -> dict[str, Any]:
        sources = [
            source_by_id(self.task, source_id)
            for source_id in self.task.required_source_ids
            if source_id != omitted_source_id
        ]
        return build_selection(
            task=self.task,
            selected_sources=sources,
            selector_name="test_missing_required_source",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector omits one required source.",
        )

    def _selection_with_distractor(self, distractor_source_id: str) -> dict[str, Any]:
        sources = [source_by_id(self.task, source_id) for source_id in self.task.required_source_ids]
        sources.append(source_by_id(self.task, distractor_source_id))
        return build_selection(
            task=self.task,
            selected_sources=sources,
            selector_name="test_selects_distractor",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector includes a distractor source.",
        )

    def test_fixture_integrity(self) -> None:
        self.assertEqual(len(self.tasks), 1)
        self.assertEqual(self.task.fixture_id, "controlled_organic_release_readiness_gate")
        self.assertEqual(len(self.task.sources), 7)
        self.assertEqual(
            self.task.required_source_ids,
            (
                "doc-release-notes-helix-2026-11",
                "doc-policy-thresholds-current",
                "doc-service-ownership-map",
                "doc-incident-followup-778",
            ),
        )
        self.assertEqual(
            self.task.distractor_source_ids,
            (
                "doc-policy-thresholds-previous",
                "doc-ops-note-local-override",
                "doc-release-notes-draft",
            ),
        )
        self.assertEqual(
            {source.source_id for source in self.task.sources if source.required},
            set(self.task.required_source_ids),
        )
        self.assertEqual(
            {source.source_id for source in self.task.sources if source.distractor},
            set(self.task.distractor_source_ids),
        )

    def test_unique_source_ids(self) -> None:
        source_ids = [source.source_id for source in self.task.sources]

        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertTrue(all(source.source_id and source.role for source in self.task.sources))

    def test_no_single_document_contains_all_required_answer_fields(self) -> None:
        required_values = set(self.task.expected_fields.values())

        for source in self.task.sources:
            source_text = source.text.lower()
            present_values = {
                value for value in required_values if value.lower() in source_text
            }
            self.assertNotEqual(
                present_values,
                required_values,
                f"{source.source_id} unexpectedly contains the full answer",
            )

    def test_complete_required_source_selection_passes(self) -> None:
        validation = validate_selection(self.task, self.fixture_selection)
        run = execute_task(
            task=self.task,
            mode="controlled_organic_multi_zone",
            selection=self.fixture_selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertTrue(validation["required_source_complete"])
        self.assertTrue(validation["distractors_omitted"])
        self.assertEqual(validation["missing_required_source_ids"], [])
        self.assertEqual(validation["unexpected_distractor_source_ids"], [])
        self.assertTrue(run["output_validation_before_repair"])
        self.assertTrue(run["honest_controlled_organic_pass"])

    def test_missing_release_notes_fails(self) -> None:
        run = self._run_missing("doc-release-notes-helix-2026-11")

        self.assertFalse(run["required_source_complete"])
        self.assertIn("doc-release-notes-helix-2026-11", run["missing_required_source_ids"])
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_missing_current_policy_fails(self) -> None:
        run = self._run_missing("doc-policy-thresholds-current")

        self.assertFalse(run["required_source_complete"])
        self.assertIn("doc-policy-thresholds-current", run["missing_required_source_ids"])
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_missing_ownership_map_fails(self) -> None:
        run = self._run_missing("doc-service-ownership-map")

        self.assertFalse(run["required_source_complete"])
        self.assertIn("doc-service-ownership-map", run["missing_required_source_ids"])
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_missing_incident_followup_fails(self) -> None:
        run = self._run_missing("doc-incident-followup-778")

        self.assertFalse(run["required_source_complete"])
        self.assertIn("doc-incident-followup-778", run["missing_required_source_ids"])
        self.assertFalse(run["honest_controlled_organic_pass"])

    def _run_missing(self, source_id: str) -> dict[str, Any]:
        selection = self._selection_without(source_id)
        return execute_task(
            task=self.task,
            mode="controlled_organic_multi_zone",
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

    def test_previous_version_policy_distractor_fails(self) -> None:
        run = self._run_with_distractor("doc-policy-thresholds-previous")

        self.assertFalse(run["distractors_omitted"])
        self.assertEqual(
            run["unexpected_distractor_source_ids"],
            ["doc-policy-thresholds-previous"],
        )
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_local_override_distractor_fails(self) -> None:
        run = self._run_with_distractor("doc-ops-note-local-override")

        self.assertFalse(run["distractors_omitted"])
        self.assertEqual(
            run["unexpected_distractor_source_ids"],
            ["doc-ops-note-local-override"],
        )
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_draft_release_note_distractor_fails(self) -> None:
        run = self._run_with_distractor("doc-release-notes-draft")

        self.assertFalse(run["distractors_omitted"])
        self.assertEqual(
            run["unexpected_distractor_source_ids"],
            ["doc-release-notes-draft"],
        )
        self.assertFalse(run["honest_controlled_organic_pass"])

    def _run_with_distractor(self, source_id: str) -> dict[str, Any]:
        selection = self._selection_with_distractor(source_id)
        return execute_task(
            task=self.task,
            mode="controlled_organic_multi_zone",
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

    def test_wrong_evidence_source_ids_fail(self) -> None:
        wrong_output = self.task.expected_answer.replace(
            "doc-service-ownership-map, doc-incident-followup-778",
            "doc-incident-followup-778, doc-policy-thresholds-previous",
        )
        output_validation = validate_output(self.task, wrong_output)
        run = execute_task(
            task=self.task,
            mode="controlled_organic_multi_zone",
            selection=self.fixture_selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
            output_override=wrong_output,
        )

        self.assertFalse(output_validation["passed"])
        self.assertEqual(
            output_validation["evidence_reference_validation"]["missing_source_ids"],
            ["doc-service-ownership-map"],
        )
        self.assertEqual(
            output_validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["doc-policy-thresholds-previous"],
        )
        self.assertFalse(run["output_validation_before_repair"])
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_fallback_makes_honest_pass_false(self) -> None:
        report = run_benchmark([self.task], selector=FailingSelector())  # type: ignore[arg-type]
        organic_run = [
            run for run in report["runs"] if run["mode"] == "controlled_organic_multi_zone"
        ][0]

        self.assertEqual(organic_run["selector"], "fixture_fallback_after_selector_error")
        self.assertFalse(organic_run["selector_success"])
        self.assertTrue(organic_run["selector_used_fallback"])
        self.assertTrue(organic_run["output_validation_before_repair"])
        self.assertFalse(organic_run["honest_controlled_organic_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 1)

    def test_output_validation_failure_makes_honest_pass_false(self) -> None:
        incomplete_output = self.task.expected_answer.replace("COMPONENT_OWNER_RELAY_GATE", "")
        run = execute_task(
            task=self.task,
            mode="controlled_organic_multi_zone",
            selection=self.fixture_selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
            output_override=incomplete_output,
        )

        self.assertFalse(validate_output(self.task, incomplete_output)["passed"])
        self.assertFalse(run["output_validation_before_repair"])
        self.assertIsNone(run["output_validation_after_repair"])
        self.assertEqual(run["output_repair_status"], "not_supported")
        self.assertFalse(run["honest_controlled_organic_pass"])

    def test_default_cli_is_provider_free(self) -> None:
        with patch.object(sys, "argv", ["run_controlled_organic_multi_zone_benchmark.py"]):
            args = _parse_args()

        selector = _build_selector_from_args(args)
        executor = _build_executor_from_args(args)

        self.assertIsInstance(selector, FixtureOrganicSelector)
        self.assertIsInstance(executor, FixtureOrganicExecutor)
        self.assertEqual(args.selector, "fixture")
        self.assertEqual(selector.provider, "deterministic_mock")
        self.assertEqual(executor.provider, "deterministic_mock")

    def test_openai_selector_prompt_uses_source_document_schema(self) -> None:
        prompt = build_openai_selector_prompt(self.task)

        self.assertIn("source documents", prompt)
        self.assertIn('"selected_source_ids"', prompt)
        self.assertIn('"source_roles"', prompt)
        self.assertIn("selected_source_ids must contain exact canonical source IDs only", prompt)
        self.assertIn('Do not prefix IDs with "DOC" or "SOURCE"', prompt)
        self.assertIn("Do not append roles in parentheses", prompt)
        self.assertIn("Do not include labels, explanations, markdown", prompt)
        self.assertIn("Valid canonical source IDs:", prompt)
        self.assertIn('"doc-release-notes-helix-2026-11"', prompt)
        self.assertIn("Do not generate the final answer", prompt)

    def test_mocked_openai_selector_exact_canonical_ids_passes(self) -> None:
        selector = OpenAIOrganicSelectorSmoke(
            model="example-openai-router",
            provider=FakeOpenAISelectorProvider(
                _selector_json(list(self.task.required_source_ids))
            ),  # type: ignore[arg-type]
        )
        report = run_benchmark([self.task], selector=selector)
        organic_run = [
            run for run in report["runs"] if run["mode"] == "controlled_organic_multi_zone"
        ][0]

        self.assertEqual(organic_run["selector"], "openai_controlled_organic_selector_smoke")
        self.assertFalse(organic_run["selector_used_fallback"])
        self.assertEqual(organic_run["selector_validation_result"], "complete")
        self.assertTrue(organic_run["honest_controlled_organic_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 0)
        self.assertEqual(
            report["summary"]["openai_selector_actual_usage"]["total_tokens"],
            720,
        )

    def test_decorated_source_ids_fail_and_trigger_fallback(self) -> None:
        decorated_ids = [
            "SOURCE doc-release-notes-helix-2026-11 (release_notes)",
            "SOURCE doc-policy-thresholds-current (policy_thresholds)",
            "SOURCE doc-service-ownership-map (ownership_map)",
            "SOURCE doc-incident-followup-778 (evidence_record)",
        ]
        selector = OpenAIOrganicSelectorSmoke(
            model="example-openai-router",
            provider=FakeOpenAISelectorProvider(_selector_json(decorated_ids)),  # type: ignore[arg-type]
        )
        report = run_benchmark([self.task], selector=selector)
        organic_run = [
            run for run in report["runs"] if run["mode"] == "controlled_organic_multi_zone"
        ][0]

        self.assertTrue(organic_run["selector_used_fallback"])
        self.assertFalse(organic_run["selector_success"])
        self.assertFalse(organic_run["honest_controlled_organic_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 1)
        metadata = organic_run["openai_selector"]
        self.assertEqual(metadata["provider"], "openai-api")
        self.assertEqual(metadata["model"], "example-openai-router")
        self.assertEqual(metadata["api_path"], "/v1/responses")
        self.assertEqual(metadata["raw_selected_source_ids"], decorated_ids)
        self.assertIn("non-canonical source IDs", metadata["error"])
        self.assertEqual(metadata["usage"]["total_tokens"], 720)

    def test_mocked_openai_selector_missing_required_source_fails(self) -> None:
        selected = [
            source_id
            for source_id in self.task.required_source_ids
            if source_id != "doc-service-ownership-map"
        ]
        selector = OpenAIOrganicSelectorSmoke(
            model="example-openai-router",
            provider=FakeOpenAISelectorProvider(_selector_json(selected)),  # type: ignore[arg-type]
        )
        report = run_benchmark([self.task], selector=selector)
        organic_run = [
            run for run in report["runs"] if run["mode"] == "controlled_organic_multi_zone"
        ][0]

        self.assertFalse(organic_run["selector_used_fallback"])
        self.assertFalse(organic_run["required_source_complete"])
        self.assertIn("doc-service-ownership-map", organic_run["missing_required_source_ids"])
        self.assertEqual(organic_run["selector_validation_result"], "incomplete")
        self.assertFalse(organic_run["honest_controlled_organic_pass"])

    def test_mocked_openai_selector_selected_distractor_fails(self) -> None:
        selected = list(self.task.required_source_ids) + ["doc-policy-thresholds-previous"]
        selector = OpenAIOrganicSelectorSmoke(
            model="example-openai-router",
            provider=FakeOpenAISelectorProvider(_selector_json(selected)),  # type: ignore[arg-type]
        )
        report = run_benchmark([self.task], selector=selector)
        organic_run = [
            run for run in report["runs"] if run["mode"] == "controlled_organic_multi_zone"
        ][0]

        self.assertFalse(organic_run["selector_used_fallback"])
        self.assertTrue(organic_run["required_source_complete"])
        self.assertFalse(organic_run["distractors_omitted"])
        self.assertEqual(
            organic_run["unexpected_distractor_source_ids"],
            ["doc-policy-thresholds-previous"],
        )
        self.assertEqual(organic_run["selector_validation_result"], "incomplete")
        self.assertFalse(organic_run["honest_controlled_organic_pass"])

    def test_report_includes_honest_fields_and_token_estimates(self) -> None:
        report = run_benchmark(self.tasks)
        summary = report["summary"]
        organic_run = [
            run for run in report["runs"] if run["mode"] == "controlled_organic_multi_zone"
        ][0]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["provider"], "deterministic_mock")
        for field in (
            "honest_controlled_organic_pass_rate",
            "required_source_completeness_rate",
            "distractor_rejection_rate",
            "fallback_count",
            "output_validation_complete_rate",
            "output_validation_after_repair_rate",
            "average_token_reduction_percent",
            "actual_usage",
        ):
            self.assertIn(field, summary)
        for field in (
            "selected_source_token_estimate",
            "suppressed_source_token_estimate",
            "total_composed_context_token_estimate",
            "full_context_baseline_token_estimate",
            "token_reduction_percent",
        ):
            self.assertIn(field, organic_run)
        self.assertEqual(organic_run["output_repair_status"], "not_supported")
        self.assertGreater(organic_run["token_reduction_percent"], 0)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "controlled_organic_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Honest controlled-organic pass rate:", markdown)
        self.assertIn("Required source completeness rate:", markdown)
        self.assertIn("Distractor rejection rate:", markdown)
        self.assertIn("Output repair status: not_supported", markdown)
        self.assertIn("Selector validation", markdown)
        self.assertIn("Full-context baseline", markdown)
        self.assertIn("Selected sources", markdown)
        self.assertIn("Suppressed sources", markdown)
        self.assertIn("Composed context", markdown)


if __name__ == "__main__":
    unittest.main()
