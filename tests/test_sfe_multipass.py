"""Tests for core multi-pass planning primitives."""

from __future__ import annotations

import json

from sfe.multipass import (
    MultiPassConfig,
    parse_multipass_plan_json,
    resolve_multipass_config,
    should_use_multipass,
    validate_multipass_plan,
)


def test_multipass_config_resolves_mode_and_limits() -> None:
    config = resolve_multipass_config(
        {
            "SFE_WORKSPACE_WRITE_MULTIPASS": "true",
            "SFE_MULTIPASS_MAX_PASSES": "6",
            "SFE_MULTIPASS_MAX_FILES_PER_PASS": "9",
            "SFE_MULTIPASS_PLANNER_MODEL": "planner-model",
        }
    )

    assert config.mode == "true"
    assert config.max_passes == 6
    assert config.max_files_per_pass == 9
    assert not hasattr(config, "planner_model")


def test_multipass_config_defaults_to_auto() -> None:
    config = resolve_multipass_config({})

    assert config.mode == "auto"
    assert config.max_passes == 10
    assert config.max_files_per_pass == 10
    assert not hasattr(config, "planner_model")


def test_multipass_heuristic_detects_large_scaffold() -> None:
    config = MultiPassConfig(mode="auto")

    assert should_use_multipass("Create a Symfony-style scaffold with 25 files", config)
    assert should_use_multipass("Créer une app complète avec 20 fichiers", config)


def test_multipass_heuristic_leaves_small_task_single_pass() -> None:
    config = MultiPassConfig(mode="auto")

    assert should_use_multipass("Patch README.md", config) is False


def test_multipass_forced_and_disabled_modes() -> None:
    assert should_use_multipass("Patch README.md", MultiPassConfig(mode="true")) is True
    assert (
        should_use_multipass(
            "Create a Symfony-style scaffold with 25 files",
            MultiPassConfig(mode="false"),
        )
        is False
    )


def test_parse_multipass_plan_rejects_invalid_json() -> None:
    issue = parse_multipass_plan_json("{bad")

    assert getattr(issue, "reason") == "invalid_plan_json"


def test_validate_multipass_plan_rejects_empty_allowed_files() -> None:
    plan = parse_multipass_plan_json(
        json.dumps(
            {
                "project_summary": "Project",
                "batches": [
                    {
                        "id": "foundation",
                        "title": "Foundation",
                        "goal": "Create foundation",
                        "allowed_files": [],
                        "depends_on": [],
                        "validation_notes": [],
                    }
                ],
            }
        )
    )

    issue = validate_multipass_plan(plan, MultiPassConfig())

    assert issue is not None
    assert issue.reason == "empty_allowed_files"
    assert issue.pass_id == "foundation"


def test_validate_multipass_plan_rejects_too_many_passes() -> None:
    plan = parse_multipass_plan_json(
        json.dumps(
            {
                "project_summary": "Project",
                "batches": [
                    {
                        "id": f"batch-{index}",
                        "title": f"Batch {index}",
                        "goal": "Create files",
                        "allowed_files": [f"file-{index}.txt"],
                        "depends_on": [],
                        "validation_notes": [],
                    }
                    for index in range(3)
                ],
            }
        )
    )

    issue = validate_multipass_plan(plan, MultiPassConfig(max_passes=2))

    assert issue is not None
    assert issue.reason == "too_many_passes"


def test_validate_multipass_plan_rejects_too_many_files_per_pass() -> None:
    plan = parse_multipass_plan_json(
        json.dumps(
            {
                "project_summary": "Project",
                "batches": [
                    {
                        "id": "foundation",
                        "title": "Foundation",
                        "goal": "Create foundation",
                        "allowed_files": ["one.txt", "two.txt", "three.txt"],
                        "depends_on": [],
                        "validation_notes": [],
                    }
                ],
            }
        )
    )

    issue = validate_multipass_plan(plan, MultiPassConfig(max_files_per_pass=2))

    assert issue is not None
    assert issue.reason == "too_many_files_per_pass"
    assert issue.pass_id == "foundation"


def test_validate_multipass_plan_rejects_future_dependency() -> None:
    plan = parse_multipass_plan_json(
        json.dumps(
            {
                "project_summary": "Project",
                "batches": [
                    {
                        "id": "templates",
                        "title": "Templates",
                        "goal": "Create templates",
                        "allowed_files": ["templates/base.html.twig"],
                        "depends_on": ["foundation"],
                        "validation_notes": [],
                    },
                    {
                        "id": "foundation",
                        "title": "Foundation",
                        "goal": "Create foundation",
                        "allowed_files": ["composer.json"],
                        "depends_on": [],
                        "validation_notes": [],
                    },
                ],
            }
        )
    )

    issue = validate_multipass_plan(plan, MultiPassConfig())

    assert issue is not None
    assert issue.reason == "invalid_dependency"
    assert issue.pass_id == "templates"
