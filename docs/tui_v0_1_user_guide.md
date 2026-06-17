# TUI V0.1 User Guide

This guide documents the current local first-party SFE-aware TUI behavior.
It is a prototype workflow guide, not a production-readiness claim.

The current local user-facing path is the TUI with `DirectBackend`. For
product-level terminology, see `sfe_product_doctrine.md`.

## What The TUI Is

The SFE-aware TUI is a command-line interactive workflow for setting a task and
running it through SFE's context-routing layer. Its primary job is to route the
task intent, answer directly when no workspace write is needed, and keep
workspace writes mechanically bounded inside an isolated worktree.

The TUI keeps the current task, selected workspace, loaded context metadata,
local routing diagnostics, latest result metadata, pending patch proposal
metadata, and optional isolated worktree session metadata in the session. It
does not run shell commands, execute tools, switch backends, push, merge, or
create pull requests. `/run` may render a natural-language console answer or
apply generated file changes inside an SFE-created worktree, depending on the
core execution-mode router. The original workspace remains protected by
Git/worktree isolation for workspace writes. Advanced primitives such as
`/patch` and `/apply-patch` remain available for debug and compatibility.
Normal workspace writes use the external Aider executable by default; Aider is
required for that path and is not vendored into SFE.

## Launch

From the repository root:

```bash
make sfe-tui
```

This loads local `.env` settings into the TUI subprocess if `.env` exists, then
runs `python -m sfe_tui`. The `.env` file is local/private, ignored by git, and
must not be committed. The TUI executor provider is selected with
`SFE_PROVIDER`, for example `SFE_PROVIDER=lemonade` or `SFE_PROVIDER=ollama`.
For normal `workspace_write`, install Aider externally and keep it on `PATH`.
On Ubuntu, Debian, and WSL, the recommended path is:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
exec $SHELL -l
pipx install aider-chat
aider --version
which aider
```

`which aider` may resolve to `~/.local/bin/aider`; that is valid if it is on
`PATH`.

You can also launch the module directly when the environment is already
configured:

```bash
python -m sfe_tui
```

For local Ollama use, Ollama must be running and the selected model must
already be pulled:

```bash
ollama pull qwen3.5:4b
SFE_PROVIDER=ollama
SFE_OLLAMA_BASE_URL=http://localhost:11434
SFE_OLLAMA_MODEL=qwen3.5:4b
SFE_OLLAMA_THINK=false
```

`SFE_OLLAMA_ROUTER_MODEL`, `SFE_OLLAMA_DISCOVERY_MODEL`, and
`SFE_OLLAMA_EXECUTOR_MODEL` can override the shared model for specific TUI
roles. `SFE_OLLAMA_THINK=false` is the default for SFE Ollama calls so
reasoning-capable local models spend output tokens on the requested router or
executor response. Ollama support is intended for local experimentation on
capable machines, not as a claim that local models outperform cloud providers.

At startup, select a workspace or accept the current directory. The TUI displays
workspace paths using safe relative labels where possible.

## Canonical Workflow

The normal first path is short:

```text
/task Build a small app
/run
```

Useful optional follow-ups:

```text
/advanced
/run-report
/context
```

`/advanced` shows the lower-level diagnostic commands. `/run-report` inspects
the last run without running it again. `/context` shows selected context
metadata. These commands are not required for the normal `/task` -> `/run`
path.

Lower-level diagnostics are available but are not the normal first path:

```text
/advanced
```

## Command Reference

### Primary Path

- `/help` and `/?`: show concise command help.
- `/status`: show current TUI state, latest result metadata, and write/shell
  boundaries.
- `/task <text>`: store the current task. Quotes around task text are optional,
  not required. Empty tasks are rejected.
- `/run`: resolve the current task through the core execution-mode router. It
  may answer directly in the TUI console or create workspace file changes
  through the Aider-backed isolated worktree pipeline. During execution, it
  prints compact `SFE:` progress lines for routing/context observability. If a
  workspace write is selected and the workspace is not yet a Git repository,
  `/run` can initialize a local repository snapshot first; it does not create a
  remote, push, run syntax checks, run tests or lint, require diff inspection,
  require human approval, or require router review. When Real Loop is enabled
  and a verifier provider is available, completed workspace writes receive a
  bounded LLM verifier/governor check that may stop or issue a targeted
  correction task for one bounded retry.
- `/reset`: clear task, context, latest routing/result, and skipped/rejected
  context and discovery state; preserve the selected workspace.
- `/advanced`: show lower-level diagnostic commands.
- `/quit` and `/exit`: exit the TUI.

### Advanced Diagnostics

- `/directory`: show the selected workspace using safe display conventions.
- `/run-report`: show diagnostics for the previous `/run` or `/run-debug`
  result without relaunching execution and without replaying progress events.
- `/context`: show loaded context segment count, opaque ids, safe source refs,
  approximate sizes/tokens, latest selected ids, and skipped/rejected metadata.
- `/ask`: send selected context plus protected task/instructions to the
  configured read-only executor/provider.
- `/workspace-status`: show whether the active workspace is the original
  workspace or an isolated worktree, plus worktree metadata and git status when
  available.

### Advanced And Maintenance

These commands are useful for debugging, compatibility, manual patch flows, and
worktree maintenance. They are not the normal first path.

- `/discover`: scan the selected workspace and build a controlled candidate
  pool for the current task.
- `/dry-run`: build the SFE contract and run a local routing preview.
- `/patch`: ask for a patch proposal only; it is not applied.
- `/apply-patch`: ask the configured router reviewer to approve or block the
  latest pending structured patch proposal.
- `/isolate`: create an SFE-owned Git Worktree from the selected Git workspace.
- `/worktree-diff`: show the active isolated worktree's git status and diff
  summary.
- `/review-worktree`: ask the configured router reviewer for `OK_PROMOTE` or
  `KO_BLOCK` over the actual worktree status, changed files, diff, and task.
- `/cleanup-worktree`: remove only the active SFE-created worktree.
- `/gc-worktrees`: dry-run report of SFE-created worktrees.
- `/gc-worktrees --clean`: remove only clean SFE-created orphan worktrees.
- `/auto-patch`: legacy macro over discover, dry-run, patch, and
  router-reviewed apply.
- `/auto-worktree`: legacy macro over isolation, patch, apply, worktree diff,
  and router-reviewed worktree review.
- `/files <paths...>`: replace context manually with provided text files for
  debug/design work.

## Execution Modes

`/run` first asks the core execution-mode router what kind of execution the
task needs:

- `console_output`: answer in the TUI console; no worktree, patch, Git
  preparation, or workspace mutation.
- `workspace_write`: create, modify, or delete workspace files through the
  isolated worktree pipeline.
- `external_action`: outside-workspace action such as sending mail, publishing,
  or opening a PR. This mode is recognized but not implemented yet, so it fails
  cleanly before workspace work starts.

## Run Progress Lines

`/run` displays compact `SFE:` lines while the core pipeline advances. They make
the routing/context layer visible without turning the TUI into a benchmark
dashboard.

Typical `workspace_write` progress looks like:

```text
SFE: run started
SFE: execution mode routing
SFE: execution mode selected: workspace_write
SFE: workspace preparation started
SFE: context discovery started
SFE: context candidates inspected: 12
SFE: relevant context selected: 3 files
SFE: estimated token reduction: 71.4%
SFE: executor prompt prepared
SFE: patch/worktree execution started
SFE: workspace boundary check completed
SFE: promotion completed
SFE: Real Loop verification started: attempt 1
SFE: Real Loop verifier verdict: pass
```

For `console_output`, `/run` shows the routing and prompt-preparation steps,
then `SFE: console answer generated` when the answer is available.

These lines are safe progress messages only. They do not display full prompts,
file contents, raw provider payloads, or benchmark results. They do not run a
live baseline-versus-spatial comparison. `/run-report` displays the latest
stored run diagnostics and does not relaunch `/run` or duplicate progress
events.

Advanced diagnostics are available through `/advanced`. Setting a new `/task`
invalidates any previous discovery result. Run `/discover` again before
`/dry-run`, `/ask`, or `/patch` unless you are using manual `/files` context.

## Discovery

When `/run` selects `workspace_write`, it performs discovery internally. The
explicit `/discover` command is retained as an advanced read-only diagnostic
primitive.

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

With `SFE_PROVIDER=ollama`, provider-backed TUI calls go to the configured
Ollama endpoint. `/dry-run` remains a local preview and still makes zero
provider calls.

Ollama troubleshooting:

- Server not running: start Ollama and check `curl http://localhost:11434/api/tags`.
- Model not found: run `ollama pull <model>` for the configured model name.
- Slow responses: use a smaller model, a more capable GPU, or increase `SFE_OLLAMA_TIMEOUT_SECONDS`.
- WSL networking: if Ollama runs inside the same WSL environment, `localhost` is expected to work. If it runs on Windows, set `SFE_OLLAMA_BASE_URL` to the reachable host URL when localhost forwarding is unavailable.

`DiscoveryResult` is render-safe: its load results are scrubbed and should be
used only for diagnostics. When the TUI later builds the real SFE contract for
`/dry-run`, `/ask`, or `/patch`, it reloads selected discovered source refs
through the explicit discovery loading boundary. That internal reload provides
full text for routing/execution without exposing raw contents in status,
discovery, context, or dry-run diagnostics.

## Dry Run

When `/run` selects `workspace_write`, it performs the needed
preflight/routing work internally. The explicit `/dry-run` command is retained
as an advanced diagnostic preview.

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
read-only executor/provider. For this read-only command, active context usually
comes from `/discover`; manual `/files` context remains available for
debug/design work and takes precedence when present.

The answer returned by the provider is displayed to the user. Diagnostics remain
limited to safe metadata such as counts, opaque segment ids, safe source refs,
provider call count, and disabled capability flags. File contents are not shown
in diagnostics.

If no executor/provider is configured, `/ask` reports that explicitly. If local
routing selects no context, it reports that no relevant segments were found
rather than treating the run as a successful answer.

## Patch

The current primary workspace-write path is `/run` when the core router selects
`workspace_write`; it applies inside an isolated worktree. The explicit `/patch`
and `/apply-patch` commands below are advanced debug/compatibility primitives.

`/patch` uses the same local selection boundary as `/ask`, but asks the
configured read-only executor/provider for a patch proposal.

The result is proposal-only:

- not applied;
- no files are modified;
- the explicit advanced primitive does not write;
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

For `workspace_write`, `/run` uses Git/worktree isolation as its main
operational guard. It may initialize a local Git repository snapshot when the
selected workspace is not already a repository, then create or reuse an
SFE-owned worktree and run Aider there. Aider may create commits inside that
worktree. SFE treats those commits as session history only and promotes the
final validated file state back to the selected source destination; the source
history does not receive Aider micro-commits directly.

`/isolate` creates an isolated Git Worktree using core SFE workspace isolation
support. The worktree is created outside the original workspace on a generated
branch named like `sfe/worktree/<session-id>`. The TUI then switches its active
workspace to the worktree, so `/patch` and `/apply-patch` operate on the
isolated copy.

The explicit `/isolate` primitive refuses non-Git workspaces and dirty source
repositories by default. `/run` can prepare a non-Git workspace by creating a
local Git snapshot before using the worktree flow. The original workspace is not
deleted, force-checked-out, merged into, pushed, or otherwise patched by the
isolation flow.

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
- discovery does not call providers, write files, or expose raw contents in
  diagnostics;
- `/run` answers directly for `console_output` without Git preparation,
  worktree creation, patch generation, or workspace mutation;
- `/run` applies workspace changes only inside an SFE-created isolated worktree
  when `workspace_write` is selected;
- `/run` recognizes `external_action` but does not implement it yet;
- `/run` does not require diff inspection, human approval, router review,
  syntax checks, tests, or lint;
- `/run` can auto-initialize a local Git snapshot for a non-Git workspace only
  on the workspace-write path, but does not create remotes or push;
- advanced `/patch` is proposal-only and does not write files;
- advanced `/apply-patch` is explicit, router-reviewed, and applies only
  pending structured full-file replacements;
- `/dry-run` makes no executor/provider call;
- `/ask` calls the configured executor only after local routing selects
  context;
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

## Legacy Text Transport

Normal `/run` workspace writes use the Aider-backed filesystem writer. The
older core text-to-file transport remains available only when
`SFE_WORKSPACE_WRITE_EXECUTOR=text` is set for legacy/debug rollback. In that
mode, text-returning providers use deterministic full-file blocks:

```text
<<<SFE_FILE path="app/index.html">
<!doctype html>
...
<<<END_SFE_FILE>>>
```

SFE writes those blocks into the controlled worktree, captures the actual
created, modified, and deleted files, and then enforces the destination-directory
boundary before promotion. Strict Git-style unified diffs remain accepted as a
compatibility path in text mode, but text transport is no longer the preferred
large multi-file generation path.

If a text-returning executor returns prose such as "I created the files" without
`SFE_FILE` blocks or a valid Git diff, `/run` fails explicitly with an
`executor_produced_no_files`-style diagnostic. The model text is not treated as
evidence that files were created. Because the runtime path is implemented in
core SFE, TUI, MCP, scripts, tests, and direct `RunPipeline` usage share the same
workspace-write behavior.

For local providers, prefer smaller and simpler workspace-write tasks, or use
explicit batches for large scaffolds. The lightweight `SFE:` progress lines
report pipeline boundaries; they do not change provider timeout behavior or add
heartbeat logic.

## Current Limitations

- `/dry-run` context preview routing is a local lexical preview, not an LLM
  router result.
- Router review for `/apply-patch` and `/review-worktree` is a semantic LLM
  review, not a formal security proof.
- Discovery is a first controlled TUI workflow, not robust general retrieval.
- Routing quality is not yet proven across repeated realistic workflows.
- Advanced `/patch` does not apply patches; advanced `/apply-patch` is required
  only for that legacy/debug proposal flow.
- `external_action` is recognized but not implemented.
- The canonical `/run` pipeline is available through the TUI; there is no
  separate stable CLI/API integration for it yet.
- There is no automatic merge, push, PR creation, arbitrary shell execution, or
  test/lint runner.
- The current test suite validates expected behavior and safety boundaries, but
  it does not establish production reliability or general practical value.

## Repository-Root Read-Only Smoke Test

This smoke uses advanced read-only diagnostics. It is useful for local
provider/configuration checks, but it is not the canonical task workflow. The
canonical task workflow is `/task <question>` followed by `/run`.

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
  through `DirectBackend`.
