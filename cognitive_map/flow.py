"""Deterministic cognitive map flow for the prototype workspace."""

from __future__ import annotations

from cognitive_map.workspace import CognitiveWorkspace


DEFAULT_PROMPT = (
    "Explain why SFE separates intent, constraints, execution, and verification."
)


def run_minimal_flow(
    user_prompt: str,
    constraints: list[str] | None = None,
    workspace: CognitiveWorkspace | None = None,
) -> dict[str, object]:
    """Run a small deterministic flow across all cognitive zones."""

    active_workspace = workspace if workspace is not None else CognitiveWorkspace()
    derived_constraints = constraints or [
        "Keep the explanation concise.",
        "Do not call external APIs.",
        "Preserve separation between routing context and execution context.",
    ]

    active_workspace.add_fragment("user_intent_zone", user_prompt)
    active_workspace.zones["user_intent_zone"].add_output_fragment(
        f"Intent extracted from prompt: {user_prompt}"
    )
    active_workspace.handoff(
        "user_intent_zone", "task_constraints_zone", "handoff_intent"
    )

    for constraint in derived_constraints:
        active_workspace.add_fragment("task_constraints_zone", constraint)
    active_workspace.zones["task_constraints_zone"].add_output_fragment(
        "Constraints prepared: " + "; ".join(derived_constraints)
    )
    active_workspace.handoff(
        "task_constraints_zone",
        "domain_knowledge_zone",
        "handoff_constraints",
    )

    active_workspace.add_fragment(
        "domain_knowledge_zone",
        "SFE uses explicit spatial metadata to separate intent, constraints, "
        "execution, verification, and output shaping.",
    )
    active_workspace.zones["domain_knowledge_zone"].add_output_fragment(
        "Domain context prepared for execution."
    )
    active_workspace.handoff(
        "domain_knowledge_zone", "execution_zone", "handoff_context"
    )

    active_workspace.add_fragment(
        "execution_zone",
        "Prepared task context combines intent, constraints, and domain context.",
    )
    active_workspace.zones["execution_zone"].add_output_fragment(
        "Execution draft: SFE separates cognitive concerns so each step can be "
        "bounded, inspected, and verified before final output."
    )
    active_workspace.handoff(
        "execution_zone", "verification_zone", "handoff_execution"
    )

    active_workspace.add_fragment(
        "verification_zone",
        "Checked that the draft references intent, constraints, execution, and "
        "verification without adding unsupported claims.",
    )
    active_workspace.zones["verification_zone"].add_output_fragment(
        "Verified output: separation keeps task state structured and auditable."
    )
    active_workspace.handoff(
        "verification_zone", "output_zone", "handoff_verified_output"
    )

    active_workspace.zones["output_zone"].add_output_fragment(
        "Final output ready from verified cognitive-map flow."
    )
    active_workspace.zones["output_zone"].set_activation(1.0)

    return active_workspace.snapshot()
