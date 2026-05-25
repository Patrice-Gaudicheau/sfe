# TUI V0.1 User Guide

This guide documents the current canonical first-party SFE-aware TUI behavior.
It is a prototype workflow guide, not a production-readiness claim.

The canonical user-facing path is the TUI with `DirectBackend`. The proxy and
proxy-backed experiments are not the primary user path and are not required for
this guide.

## What The TUI Is

The SFE-aware TUI is a command-line interactive workflow for setting a task,
discovering a controlled pool of workspace context, previewing local context
routing, and optionally asking a configured executor/provider for an answer or
patch proposal.

The TUI keeps the current task, selected workspace, loaded context metadata,
local routing diagnostics, latest ask/patch result, pending patch proposal
metadata, and optional isolated worktree session metadata in the session. It
does not run shell commands, execute tools, or switch backends. Automatic writes
are disabled; explicit `/apply-patch` is available for applying the latest
pending patch proposal after router review.

## Launch

From the repository root:

```bash
make sfe-tui
```

This loads local `.env` settings into the TUI subprocess if `.env` exists, then
runs `python -m sfe_tui`. The `.env` file is local/private, ignored by git, and
must not be committed. The TUI executor provider is selected with
`SFE_PROVIDER`, for example `SFE_PROVIDER=lemonade`.

You can also launch the module directly when the environment is already
configured:

```bash
python -m sfe_tui
```

At startup, select a workspace or accept the current directory. The TUI displays
workspace paths using safe relative labels where possible.

## Canonical Workflow

1. Check the selected workspace:

   ```text
   /directory
   ```

2. Set the task:

   ```text
   /task <question>
   ```

3. Discover workspace context:

   ```text
   /discover
   ```

4. Preview local routing without provider calls or writes:

   ```text
   /dry-run
   ```

5. Inspect safe context metadata and selected segment ids:

   ```text
   /context
   ```

6. Ask a read-only question using selected context:

   ```text
   /ask
   ```

7. Optionally request a patch proposal without applying it:

   ```text
   /patch
   ```

8. Optionally apply the latest pending patch proposal explicitly:

   ```text
   /apply-patch
   ```

9. Clear the session state while preserving the workspace:

   ```text
   /reset
   ```

For isolated write experiments, use `/isolate` before `/patch` so writes happen
inside an SFE-created Git Worktree instead of the original checkout. The macro
commands `/auto-patch` and `/auto-worktree` run the existing safe handlers in
sequence and stop on failure or router `KO_BLOCK`; they do not add merge, push,
PR, shell execution, or test-runner behavior.

## Command Reference

- `/help`: show concise command help.
- `/directory`: show the selected workspace using safe display conventions.
- `/status`: show safe TUI state, latest result metadata, and disabled
  capabilities.
- `/task <text>`: store the current task. Empty tasks are rejected.
- `/discover`: scan the selected workspace and build a controlled candidate
  pool for the current task. Empty tasks are rejected.
- `/dry-run`: build the SFE contract and run a local routing preview. After a
  task is set, this requires `/discover` unless manual `/files` context exists.
- `/context`: show loaded context segment count, opaque ids, safe source refs,
  approximate sizes/tokens, latest selected ids, and skipped/rejected metadata.
- `/ask`: send selected context plus protected task/instructions to the
  configured read-only executor/provider. After a task is set, this requires
  `/discover` unless manual `/files` context exists.
- `/patch`: ask for a patch proposal only. The proposal is not applied. After a
  task is set, this requires `/discover` unless manual `/files` context exists.
- `/apply-patch`: ask the configured router reviewer to approve or block the
  latest pending structured patch proposal. If approved, write the proposed
  full file replacements inside the selected workspace.
- `/isolate`: create an SFE-owned Git Worktree from the selected Git workspace
  and switch the active TUI workspace to that worktree. Dirty source
  workspaces are refused by default.
- `/workspace-status`: show whether the active workspace is the original
  workspace or an isolated worktree, plus worktree metadata and git status when
  available.
- `/worktree-diff`: show the active isolated worktree's git status and diff
  summary.
- `/review-worktree`: ask the configured router reviewer for `OK_PROMOTE` or
  `KO_BLOCK` over the actual worktree status, changed files, diff, and task.
  `OK_PROMOTE` does not merge, push, commit, create a PR, or mutate the source
  branch.
- `/cleanup-worktree`: remove only the active SFE-created worktree and restore
  the original source workspace as the active workspace.
- `/gc-worktrees`: dry-run report of SFE-created worktrees found from the
  selected source workspace. It does not remove anything.
- `/gc-worktrees --clean`: remove only clean SFE-created orphan worktrees and
  protect the active TUI worktree session. Dirty worktrees are reported and
  skipped.
- `/auto-patch`: macro command that runs the existing discover, dry-run,
  patch, and router-reviewed apply flow. It stops on failure or router
  `KO_BLOCK`.
- `/auto-worktree`: macro command that creates isolation if needed, then runs
  the existing patch, apply, worktree-diff, and router-reviewed worktree review
  flow. It stops on failure or `KO_BLOCK` and leaves the worktree available for
  inspection.
- `/files <paths...>`: replace context manually with the provided text files
  for debug/design work. Directory inputs and unsupported files are rejected or
  skipped with a reason. This remains available but is not the normal
  human-facing workflow.
- `/reset`: clear task, context, latest routing/result, and skipped/rejected
  context and discovery state; preserve the selected workspace.
- `/quit` and `/exit`: exit the TUI.

Setting a new `/task` invalidates any previous discovery result. Run
`/discover` again before `/dry-run`, `/ask`, or `/patch` unless you are using
manual `/files` context.

## Discovery

`/discover` uses the reusable core discovery layer in `sfe/discovery.py`. It
scans only inside the selected workspace and builds a bounded, deterministic
candidate pool for the current task.

Discovery is the first controlled TUI discovery workflow. It is not a claim of
robust general retrieval or production readiness. The architecture boundary is:

```text
Discoverer -> Router -> Executor
```

In the current TUI:

- the Discoverer is core workspace discovery in `sfe/discovery.py`, backed by
  the configured discovery router in `sfe/discovery_router.py`;
- the `/dry-run` context preview is still the provider-free local lexical
  preview;
- the Executor is the configured executor used by `DirectBackend`.

Discovery builds a metadata-only workspace map, asks the configured discovery
router which files to inspect, and locally revalidates selected paths before
loading them. It does not write files, run shell commands, execute tools, or
expose raw file contents in diagnostics. It excludes obvious unsafe/local/generated
inputs such as `.env`, cache directories, local logs, local databases, JSONL
streams, binary/non-UTF-8 files, and common build artifacts.

`DiscoveryResult` is render-safe: its load results are scrubbed and should be
used only for diagnostics. When the TUI later builds the real SFE contract for
`/dry-run`, `/ask`, or `/patch`, it reloads selected discovered source refs
through the explicit discovery loading boundary. That internal reload provides
full text for routing/execution without exposing raw contents in status,
discovery, context, or dry-run diagnostics.

## Dry Run

`/dry-run` is a local preview. It uses the provider-free
`local_lexical_preview` router to estimate which loaded or discovered context
segments would be selected for the current task.

It reports preflight state, selected opaque segment ids, safe source refs,
approximate token counts, fallback reasons where available, and safety flags.
It does not call the executor/provider, write files, execute shell commands, or
apply patches.

## Ask

`/ask` routes active context locally, then sends only the selected context
segments, protected instructions, and protected task to the configured
read-only executor/provider. In the canonical path, active context comes from
`/discover`; manual `/files` context remains available for debug/design work
and takes precedence when present.

The answer returned by the provider is displayed to the user. Diagnostics remain
limited to safe metadata such as counts, opaque segment ids, safe source refs,
provider call count, and disabled capability flags. File contents are not shown
in diagnostics.

If no executor/provider is configured, `/ask` reports that explicitly. If local
routing selects no context, it reports that no relevant segments were found
rather than treating the run as a successful answer.

## Patch

`/patch` uses the same local selection boundary as `/ask`, but asks the
configured read-only executor/provider for a patch proposal.

The result is proposal-only:

- not applied;
- no files are modified;
- automatic writes are disabled;
- explicit `/apply-patch` is available when a structured proposal is pending.

The provider is asked for structured full-file replacements. The stored proposal
is the full replacement content for each touched file, and that full replacement
content is the apply source of truth. The TUI displays a readable unified diff
preview, but that diff is computed locally by SFE from the current file content
and the proposed replacement content. Provider-supplied diff previews are not
trusted for display, application, or router review. `/patch` does not apply the
proposal, run shell commands, execute tools, or modify the workspace.

`/apply-patch` calls the configured router reviewer before writing. Router
`KO_BLOCK` writes nothing and keeps the pending proposal. Router `OK_APPLY`
allows the TUI to write the proposed full replacement contents; the pending
proposal is cleared only after successful writes. Physical write failures are
reported separately from router rejection and keep the pending proposal.

The router review for `/apply-patch` is a semantic LLM review. It receives the
original task, selected/discovered context metadata, current file contents when
readable, proposed full replacements, allowed paths, and the SFE-computed
effective diff. It is intended to catch unrelated or surprising edits, but it is
not a formal security proof.

## Worktree Isolation

`/isolate` creates an isolated Git Worktree using core SFE workspace isolation
support. The worktree is created outside the original workspace on a generated
branch named like `sfe/worktree/<session-id>`. The TUI then switches its active
workspace to the worktree, so `/patch` and `/apply-patch` operate on the
isolated copy.

The default policy refuses non-Git workspaces and dirty source repositories.
The original workspace is not deleted, force-checked-out, merged into, pushed,
or otherwise mutated by the isolation flow.

`/review-worktree` collects the actual worktree git status, changed files, and
git diff, then asks the configured router reviewer for `OK_PROMOTE` or
`KO_BLOCK`. This review is semantic and task-oriented; it does not repair the
worktree and does not prove security or correctness. In V1, `OK_PROMOTE` is
only a review result. There is no automatic merge, push, commit, PR creation,
source-branch mutation, arbitrary shell execution, or test/lint runner.

`/cleanup-worktree` removes only the active SFE-created worktree. `/gc-worktrees`
is dry-run by default and reports SFE-created worktrees found from the source
workspace. `/gc-worktrees --clean` removes only clean SFE-created orphan
worktrees; it protects the active TUI worktree session and skips dirty
worktrees.

## Macro Commands

`/auto-patch` and `/auto-worktree` are convenience macros over the existing
handlers. They do not bypass router review and do not introduce new execution
capabilities.

`/auto-patch` runs discovery if needed, then the dry-run, patch, and
router-reviewed apply path. It writes only if `/apply-patch` receives
`OK_APPLY`.

`/auto-worktree` creates isolation if needed, preserves manually selected
`/files` context across the worktree switch, then runs patch, apply,
worktree-diff, and router-reviewed worktree review. It never merges, pushes,
commits, creates a PR, or cleans up automatically.

## Safety Guarantees

The current TUI behavior intentionally keeps these boundaries:

- no shell execution;
- no tool execution;
- no backend switching;
- no proxy in the canonical TUI path;
- discovery does not call providers, write files, or expose raw contents in
  diagnostics;
- automatic writes disabled; explicit `/apply-patch` available;
- `/dry-run` makes no executor/provider call;
- `/ask` calls the configured executor only after local routing selects
  context;
- `/patch` is proposal-only and does not write files;
- `/apply-patch` is explicit, router-reviewed, and applies only pending
  structured full-file replacements;
- displayed patch diffs are computed locally from actual proposed full-file
  replacements; provider diff previews are untrusted diagnostics only;
- `/review-worktree` reviews the actual worktree git diff and status;
- `OK_PROMOTE` does not merge, push, commit, create a PR, or mutate the source
  branch;
- `/gc-worktrees` is dry-run by default and clean mode targets only
  SFE-created clean orphan worktrees;
- workspace and source paths are displayed using safe relative labels where
  possible;
- diagnostics do not display raw file contents, request bodies, provider
  payloads, API keys, or authorization headers.

## Current Limitations

- `/dry-run` context preview routing is a local lexical preview, not an LLM
  router result.
- Router review for `/apply-patch` and `/review-worktree` is a semantic LLM
  review, not a formal security proof.
- Discovery is a first controlled TUI workflow, not robust general retrieval.
- Routing quality is not yet proven across repeated realistic workflows.
- `/patch` does not apply patches; `/apply-patch` is required for writes.
- There is no CLI/API pipeline integration for the canonical TUI workflow yet.
- There is no automatic merge, push, PR creation, arbitrary shell execution, or
  test/lint runner.
- The proxy remains standby experimental compatibility and observability
  infrastructure; it is not the canonical user path.
- The current test suite validates expected behavior and safety boundaries, but
  it does not establish production reliability or general practical value.

## Repository-Root Smoke Test

From the repository root:

```bash
make sfe-tui
```

In the TUI, accept the current workspace, then run:

```text
/status
/task Explique en quelques phrases comment SFE_PROVIDER est résolu.
/discover
/dry-run
/context
/ask
/status
/quit
```

Expected observations:

- `/status` reports `backend: direct`;
- `/discover` reports safe candidate metadata and does not show task text,
  raw file contents, absolute workspace paths, request bodies, authorization
  headers, or API keys;
- `/dry-run` reports local preview diagnostics and `provider calls made: 0`;
- `/dry-run` uses discovered context;
- `/context` shows opaque segment ids, safe source refs, approximate
  sizes/tokens, and selection metadata, not raw file contents;
- `/ask` requires a configured executor/provider and may report safe provider
  errors if the configured provider is unavailable;
- with `SFE_PROVIDER=lemonade` and Lemonade reachable, `/ask` can complete
  through `DirectBackend`;
- no proxy is used.
