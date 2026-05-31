# SFE Continuity And Orientation Layer

This note defines a small SFE-side continuity and orientation layer inspired by
TPCE vocabulary. It is an architecture boundary, not an implementation plan for
importing TPCE into SFE.

Current status note: this document predates the `/run`-first TUI workflow and
should be read as orientation vocabulary, not as current user guidance. The
current primary editing path is `/task <request>` followed by `/run`;
discovery, patch, apply, review, and manual file commands remain available as
advanced/debug primitives.

## Decision

SFE should not integrate TPCE directly right now.

SFE should also not ignore TPCE. The TUI is already accumulating concepts that
overlap with TPCE's continuity vocabulary: active workspace, active task,
discovered files, selected context, pending patch proposals, router review,
safe apply boundaries, worktree isolation, and continuity between discovery,
patch, review, and apply.

The current direction is therefore:

- keep TPCE technically separate from SFE;
- introduce a small SFE-native continuity/orientation vocabulary;
- keep the vocabulary compatible with TPCE concepts where useful;
- avoid a runtime dependency on TPCE until TPCE has a stable integration
  surface that fits live Git workspaces and SFE workflows.

## Why Not Integrate TPCE Directly Now

TPCE is currently a deterministic continuity laboratory. Its implemented
surface is centered on fixtures, explicit scenarios, validators, diagnostic
events, audit fields, state records, and deterministic reports.

That is useful, but it is not yet the runtime shape SFE needs. TPCE is not
currently:

- a service for SFE;
- a CLI workflow for SFE;
- an LLM-backed router;
- a reader of live Git repositories;
- a semantic workspace discovery engine;
- a patch proposal, review, and apply workflow;
- a worktree isolation layer.

Direct integration now would force SFE to adapt an experimental fixture
verification suite to a live workspace mutation workflow. That would likely
produce premature adapters, unstable abstractions, and a dependency boundary
that would be hard to keep honest.

The safer boundary is to adopt compatible concepts, not TPCE runtime code.

## Why Use TPCE-Compatible Vocabulary

SFE needs continuity vocabulary because the TUI must answer practical workflow
questions:

- Which workspace is active?
- Which task is active?
- Which files were discovered?
- Which files were selected for provider context?
- Which files were inspected, proposed, reviewed, modified, or created?
- Is the pending patch still connected to the same task and workspace?
- Did the provider propose a file outside the active evidence trace?
- Did the system drift into the wrong workspace or worktree?

Without explicit terms, these concerns become scattered flags and ad hoc
checks. TPCE provides useful names for the underlying shape: trace, evidence,
expected values, actual values, diagnostic events, continuity uncertainty, and
rupture. SFE should use those ideas in a narrower engineering sense.

This does not mean SFE should adopt TPCE's full rupture taxonomy, cognitive
framing, or diagnostic-question layer.

## Concepts

### WorkspaceOrientation

Role:

`WorkspaceOrientation` records where SFE believes it is operating.

Probable fields:

- `workspace_root`: active workspace root as a workspace identity.
- `launch_cwd`: directory from which the TUI was launched.
- `active_workspace`: original checkout or isolated worktree path.
- `workspace_mode`: source checkout, SFE worktree, or unknown.
- `worktree_session_id`: SFE-created worktree session id, if any.
- `git_head_ref`: optional current branch or commit identity when available.
- `created_at_step`: logical workflow step when orientation was captured.

TPCE link:

This is closest to TPCE's spatial continuity, but SFE's "space" is a live
workspace and optional worktree, not a fixture graph.

Limit for now:

Do not model the repository as a TPCE graph. Do not introduce TPCE spatial
validators. Keep this as a compact workspace identity record.

### TaskTrace

Role:

`TaskTrace` records the active user task and lets SFE detect when later actions
are no longer connected to the same request.

Probable fields:

- `task_text`: current protected user task, where storage is appropriate.
- `task_hash`: stable hash used when the raw text should not be repeated.
- `task_started_at_step`: logical step when the task became active.
- `task_source`: user command, macro command, or future automation.
- `supersedes_task_hash`: previous task hash, if a new task replaces one.
- `status`: active, superseded, completed, or reset.

TPCE link:

This is related to TPCE's autobiographical and temporal continuity in a narrow
technical sense: it preserves what the system is currently trying to do and
whether later claims still belong to that task.

Limit for now:

Do not implement broad autobiographical self-modeling. Do not add identity,
role, capability, or narrative claims beyond the task and workflow state needed
by SFE.

### EvidenceReference

Role:

`EvidenceReference` records what SFE has actually seen, selected, or acted on.
It should be path-based and content-safe by default.

Probable fields:

- `source_ref`: workspace-relative path.
- `evidence_kind`: discovered, loaded, selected, proposed, reviewed, modified,
  created, rejected, or skipped.
- `origin_step`: discovery, manual files, router selection, patch proposal,
  router review, apply, or worktree review.
- `reason`: local reason, router reason, provider reason, or guard reason.
- `content_hash`: optional hash for loaded content snapshots.
- `size_bucket`: safe approximate size metadata.
- `warning_reason`: secret marker warning, decode warning, or other safe flag.

TPCE link:

This maps most directly to TPCE trace references and supporting evidence refs.
It lets SFE distinguish "the provider mentioned this path" from "SFE actually
loaded and inspected this path."

Limit for now:

Do not store raw file contents in diagnostic traces by default. Do not use
EvidenceReference as authorization to bypass local path, secret, or workspace
guards.

### ContinuityState

Role:

`ContinuityState` is an optional aggregate that ties orientation, task, evidence,
pending proposals, and decisions into one inspectable workflow state.

Probable fields:

- `orientation`: current `WorkspaceOrientation`.
- `task_trace`: current `TaskTrace`.
- `evidence_refs`: ordered list of `EvidenceReference` records.
- `selected_source_refs`: files selected for executor context.
- `pending_patch_ref`: pending patch id or task hash, if any.
- `decision_events`: discovery, routing, patch parse, router review, apply,
  and worktree review decisions.
- `continuity_issues`: detected local issues or warnings.

TPCE link:

This is analogous to a small SFE-specific continuity state and diagnostic audit
record. It borrows the idea of expected vs actual state, but keeps the domain
limited to workspace workflow correctness.

Limit for now:

Do not create a general cognitive state engine. Do not make this a hard
dependency for every SFE module until the shape is proven in the TUI.

## Simple Continuity Issues SFE Can Detect

SFE can detect useful discontinuities without importing TPCE:

- `task_missing_for_patch`: `/patch` or `/apply-patch` is requested without an
  active task.
- `workspace_changed_after_discovery`: the active workspace or worktree changed
  after discovery created the active evidence trace.
- `context_changed_after_patch`: the pending patch was created from an earlier
  task hash, selected context, or workspace orientation.
- `patch_touches_path_outside_trace`: a patch modifies a file that was not in
  the active selected, discovered, manually loaded, or explicitly allowed trace.
- `provider_proposed_uninspected_file`: the provider proposes a path that SFE
  never discovered, loaded, or inspected.
- `review_context_incomplete`: router review is asked to approve a patch while
  current file content, selected refs, or discovery metadata are missing.
- `worktree_orientation_mismatch`: apply or promote is requested against a
  different worktree session than the one that produced the pending patch.

These are engineering issues, not TPCE rupture classes. They may later be
exported as rupture-like events, but SFE should keep the runtime labels
practical and workflow-specific.

## Semantic Discovery Support

The future default `/discover` should become semantic rather than purely local
lexical. A continuity/orientation layer helps that change in three ways.

First, semantic discovery can produce evidence refs before loading content:
workspace-relative paths, approximate sizes, safe type hints, and selection
reasons. This separates path-level relevance from content inspection.

Second, router-selected paths can be compared against the active task and
workspace orientation. If the task or workspace changes, the discovery trace can
be marked stale rather than silently reused.

Third, later `/patch` and `/apply-patch` can check whether provider output is
grounded in the semantic discovery trace. The provider may still create new safe
files when the task allows it, but that should be represented explicitly as a
creation decision, not confused with an inspected existing file.

## Future TPCE-Compatible Export

SFE may later export a structured trace file such as `sfe_trace_export.json`.
That export should be optional and should not require TPCE at runtime.

Possible export shape:

```json
{
  "trace_type": "sfe.workflow_trace",
  "schema_version": "0.1",
  "workspace_orientation": {},
  "task_trace": {},
  "evidence_refs": [],
  "decision_events": [],
  "continuity_issues": []
}
```

The export should contain:

- relative paths, not absolute local secrets;
- task hashes where raw task text is not needed;
- selected, inspected, proposed, reviewed, modified, and created refs;
- expected vs actual fields for local continuity checks;
- router decisions and risk levels where available;
- no raw `.env`, `.git`, provider payloads, API keys, or hidden prompt content.

TPCE could later consume this file as fixture-like evidence if a stable bridge
is designed. SFE should not import TPCE to produce it.

## Near-Term Boundary

Near term, SFE should document and prototype only the minimal vocabulary needed
for TUI workflow correctness:

1. workspace orientation;
2. task trace;
3. evidence references;
4. continuity issues;
5. optional trace export shape.

The layer should remain small, deterministic, and local. It should support
semantic discovery and safe patch workflows without becoming a generalized TPCE
runtime inside SFE.
