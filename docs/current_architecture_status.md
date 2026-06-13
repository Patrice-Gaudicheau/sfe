# Current SFE Architecture Status

This note freezes the current architecture status after the latest first-party
TUI work. It is a status boundary, not a production-readiness claim.

For the current user-facing TUI workflow and command reference, see
[tui_v0_1_user_guide.md](tui_v0_1_user_guide.md).

For the current product doctrine, see
[sfe_product_doctrine.md](sfe_product_doctrine.md).

For the planned local MCP control surface and the TUI/MCP ISO runtime
requirement, see
[sfe_mcp_local_control_surface.md](sfe_mcp_local_control_surface.md).

## Current Local User Path

SFE core is the routing/context engine: routing, context selection, bounded
execution, validation, and observability. The SFE-aware TUI is the current local
user-facing surface for that engine. It should remain CLI/TUI-first for now,
but it is not the conceptual source of truth for SFE.

The current TUI backend is `DirectBackend`. It works from an explicit SFE
contract: selected workspace, protected task, protected instructions, explicit
context segments, reducibility metadata, local routing diagnostics, an executor
boundary, console answers, and mechanically bounded writes in an isolated
worktree when workspace file changes are selected.

The current primary TUI workflow is:

```text
/task <question>
/run
```

`/run` is the current primary TUI action. It first asks the core
execution-mode router
whether the task should produce a console answer, write workspace files, or be
treated as an outside-workspace action. `console_output` returns a
natural-language answer with no worktree or patch. `workspace_write` discovers
workspace context, builds the internal routing/preflight state needed for a
reduced executor payload, and writes changes into an SFE-created Git worktree.
Text-only API providers transport those changes as deterministic full-file
`SFE_FILE` blocks; strict Git diffs remain a compatibility path. SFE then
enforces one boundary: every created, modified, or deleted path must be inside
the selected destination directory before promotion. It does not require human
approval, diff inspection, router review, patch hunk/preimage validation, patch
repair, syntax checks, tests, or lint before promotion. `external_action` is
recognized but not implemented yet and fails cleanly before workspace work
starts.

`workspace_write` is the developer worktree execution mode. For text-only
providers, model text is a file transport and audit artifact rather than a
promotion contract: `SFE_FILE` blocks are written into the controlled worktree,
then the resulting filesystem changes are checked against the
destination-directory boundary.

Large `workspace_write` tasks may use multi-pass execution. In that path the
Router designs and validates the strict JSON batch plan before execution
proceeds. The Executor does not design the global plan; it only makes the
changes for each already-validated batch. Batch outputs use the same worktree
isolation, actual-change capture, destination-boundary check, and promotion
machinery as normal workspace writes.

The worktree is the main operational guard for `workspace_write`. If the
selected workspace is already inside a Git repository, `/run` uses that
repository to create or reuse an SFE-owned worktree. If the selected workspace
is not yet a Git repository, `/run` may initialize a local repository snapshot
first, create an initial commit, and then continue with the isolated worktree
flow. It does not configure a remote, push, merge, create a PR, or mutate the
source branch with the generated patch.

Advanced/debug commands remain available for compatibility and inspection:

```text
/discover
/dry-run
/patch
/apply-patch
/isolate
/worktree-diff
/review-worktree
/cleanup-worktree
/gc-worktrees
/auto-patch
/auto-worktree
/files
```

The underlying routing/context flow still follows the intended architecture
boundary:

```text
Route task -> select bounded context -> execute -> validate -> observe
```

The Discoverer is the reusable core discovery layer in `sfe/discovery.py`. It
scans the selected workspace, builds a bounded candidate pool, keeps
`DiscoveryResult` render-safe. `/discover` now calls the configured discovery
router with a metadata-only workspace map, then locally revalidates selected
paths before loading them. It does not write files, run shell commands, or
expose raw file contents in diagnostics. Full text is reloaded later through the
explicit discovery loading boundary when the TUI builds an SFE contract.

The `/dry-run` context-selection preview remains the provider-free local lexical
preview for now. It is not an LLM router result and should not be described as
robust general retrieval. The Executor remains the configured executor behind
`DirectBackend`. Separate configured router-review calls are used by the
advanced `/apply-patch` and `/review-worktree` flows; those reviews are
semantic checks, not formal security proofs. They are not part of the canonical
`/run` path.

During `/run`, the TUI renders compact `SFE:` progress lines for routing,
context, prompt preparation, workspace-write execution, validation, promotion,
or console answer generation. These lines are lightweight observability. They
are not benchmark output and do not run baseline-versus-spatial comparisons.

The currently validated TUI commands are:

- `/help`
- `/?`
- `/advanced`
- `/directory`
- `/status`
- `/task`
- `/run`
- `/discover`
- `/dry-run`
- `/context`
- `/ask`
- `/patch`
- `/apply-patch`
- `/isolate`
- `/workspace-status`
- `/worktree-diff`
- `/review-worktree`
- `/cleanup-worktree`
- `/gc-worktrees`
- `/auto-patch`
- `/auto-worktree`
- `/files`
- `/reset`

`/discover`, `/dry-run`, `/patch`, `/apply-patch`, `/isolate`,
`/worktree-diff`, `/review-worktree`, `/auto-patch`, `/auto-worktree`, and
`/files` remain executable advanced/debug or legacy compatibility commands, not
the recommended user flow. They are intentionally omitted from the simplified
default `/help` output.

`/dry-run` uses the local provider-free `local_lexical_preview` router. It is
deterministic and useful for previewing selected segment ids, token estimates,
score categories, and fallback reasons. It is not an LLM router result.
After a task is set, `/dry-run` requires `/discover` unless manual `/files`
context exists. It makes zero provider calls.

`/ask` uses `DirectBackend`, selected context, protected instructions, and the
protected task to produce a read-only answer. It does not switch backends,
write files, execute shell commands, or run an agent loop. After a task is set,
`/ask` requires `/discover` unless manual `/files` context exists. It calls the
configured executor only after local routing selected context.

`/patch` is proposal-only. It asks the configured executor for structured
full-file replacement proposals, stores them as pending state, and never writes
files. The displayed unified diff is computed locally by SFE from current file
content and proposed replacement content; provider-supplied diff previews are
untrusted diagnostics only. After a task is set, `/patch` requires `/discover`
unless manual `/files` context exists.

`/apply-patch` is the explicit write boundary. It asks the configured router
reviewer for `OK_APPLY` or `KO_BLOCK` and writes the pending full-file
replacements only after `OK_APPLY`. `KO_BLOCK` writes nothing and keeps the
pending proposal for inspection.

Git Worktree isolation is available through `/isolate`. It creates an
SFE-owned worktree outside the source checkout, switches the active TUI
workspace to that worktree, and lets `/patch` plus `/apply-patch` modify only
the isolated copy. `/review-worktree` reviews the actual git status and diff
with the configured router reviewer and returns `OK_PROMOTE` or `KO_BLOCK`.
`OK_PROMOTE` does not merge, push, commit, create a PR, or mutate the source
branch. `/cleanup-worktree` removes only the active SFE-created worktree.
`/gc-worktrees` is dry-run by default; `/gc-worktrees --clean` removes only
clean SFE-created orphan worktrees and protects the active TUI session.

`/auto-patch` and `/auto-worktree` are legacy macro commands over the existing
handlers. They stop on failure or router `KO_BLOCK`, preserve the same router
review boundaries, and do not introduce shell execution, test/lint execution,
merge, push, PR creation, or automatic cleanup.

`/files` remains available as manual/debug context loading. It is no longer the
normal human-facing workflow and should not be presented as the recommended TUI
path.

Setting `/task` invalidates previous discovery. `/reset` clears task, manual
context, discovery state, latest routing/result, and skipped/rejected context
state while preserving the selected workspace.

## Provider Selection

Provider selection for SFE runtime roles can be split with
`SFE_PROVIDER_ROUTER`, `SFE_PROVIDER_DISCOVERY`, and
`SFE_PROVIDER_EXECUTOR`. Router and executor role-specific values override
`SFE_PROVIDER`; blank or absent role values fall back to `SFE_PROVIDER`, then
the surface default. Discovery first checks `SFE_PROVIDER_DISCOVERY`, then
falls back to `SFE_PROVIDER_ROUTER`, then `SFE_PROVIDER`, then the surface
default.

CodexCLI is exposed on public SFE surfaces as `SFE_PROVIDER=codexcli` or through
role-specific provider selection. `SFE_CODEXCLI_ROUTER_MODEL`,
`SFE_CODEXCLI_DISCOVERY_MODEL`, and `SFE_CODEXCLI_EXECUTOR_MODEL` are the
CodexCLI model selectors. Blank or absent discovery model falls back to
`SFE_CODEXCLI_ROUTER_MODEL`, then the CodexCLI router default. Role-specific
`SFE_CODEXCLI_ROUTER_EFFORT`, `SFE_CODEXCLI_DISCOVERY_EFFORT`, and
`SFE_CODEXCLI_EXECUTOR_EFFORT` override the legacy shared
`SFE_CODEXCLI_REASONING_EFFORT`; blank or absent discovery effort falls back to
router effort, then the shared value. The benchmark-local `openai-codexcli`
name is retained for benchmark history and internal dispatch compatibility. In
DEV patch mode CodexCLI proposes text only; SFE still owns discovery path
validation, text-to-file or diff parsing, worktree isolation, application, and
rejection. Filesystem-capable executor paths can later use the real controlled
worktree as the source of truth. Google discovery routing uses
`SFE_GOOGLE_DISCOVERY_MODEL`, then
`SFE_GOOGLE_MODEL`, then the Google provider default.

The full CodexCLI `/run` role split is:

```env
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=codexcli
SFE_PROVIDER_EXECUTOR=codexcli
SFE_CODEXCLI_DISCOVERY_MODEL="gpt-5.5"
SFE_CODEXCLI_DISCOVERY_EFFORT="high"
```

## What Remains Unproven

Before making practical value claims, SFE still needs evidence that the
primary `/run` path can repeatedly choose the right execution mode, produce
useful console answers, and deliver useful context reduction for workspace
writes without hurting task correctness.

The minimum proof still missing includes:

- repeated TUI runs on realistic tasks, not only unit tests or anecdotes;
- strict success criteria that do not count fallback, repair, or hidden full
  context substitution as success;
- measured selected-context quality, token reduction, latency, and provider
  cost;
- failure reporting for no-match routing, over-selection, under-selection, and
  provider errors;
- repeated evidence for the routed `/run` flow, including console answers and
  workspace writes, plus the advanced router-reviewed write/worktree flows
  beyond unit tests and manual validation;
- stronger evidence for real Responses streaming context replacement before it
  is treated as generally usable;
- clearer operational guidance for secrets, logs, provider limits, and local
  deployment boundaries.

The current status is therefore: SFE core plus the local TUI `DirectBackend`
surface is the primary current direction; `workspace_write` is the accepted
developer execution mode; practical value remains to be demonstrated with
controlled, repeatable workflows.
