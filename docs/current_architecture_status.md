# Current SFE Architecture Status

This note freezes the current architecture status after the latest first-party
TUI work. It is a status boundary, not a production-readiness claim.

For the current user-facing TUI workflow and command reference, see
[tui_v0_1_user_guide.md](tui_v0_1_user_guide.md).

## Canonical User Path

The SFE-aware TUI is the canonical user-facing path for current SFE workflow
development. It should remain CLI/TUI-first for now.

The canonical TUI backend is `DirectBackend`. It works from an explicit SFE
contract: selected workspace, protected task, protected instructions, explicit
context segments, reducibility metadata, local routing diagnostics, and a
executor boundary plus explicit router-reviewed write boundaries.

The current canonical TUI workflow is:

```text
/task <question>
/discover
/dry-run
/context
/ask
```

Write-oriented experiments use explicit commands rather than automatic writes:

```text
/patch
/apply-patch
```

The isolated worktree path is:

```text
/isolate
/patch
/apply-patch
/worktree-diff
/review-worktree
/cleanup-worktree
```

This is the first controlled TUI discovery workflow. It follows the intended
architecture boundary:

```text
Discoverer -> Router -> Executor
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
`DirectBackend`. Separate configured router-review calls are used for
`/apply-patch` and `/review-worktree`; those reviews are semantic checks, not
formal security proofs.

The currently validated TUI commands are:

- `/help`
- `/directory`
- `/status`
- `/task`
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

`/dry-run` uses the local provider-free `local_lexical_preview` router. It is
deterministic and useful for previewing selected segment ids, token estimates,
score categories, and fallback reasons. It is not an LLM router result.
After a task is set, `/dry-run` requires `/discover` unless manual `/files`
context exists. It makes zero provider calls.

`/ask` uses `DirectBackend`, selected context, protected instructions, and the
protected task to produce a read-only answer. It does not use the proxy, switch
backends, write files, execute shell commands, or run an agent loop. After a
task is set, `/ask` requires `/discover` unless manual `/files` context exists.
It calls the configured executor only after local routing selected context.

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

`/auto-patch` and `/auto-worktree` are macro commands over the existing
handlers. They stop on failure or router `KO_BLOCK`, preserve the same router
review boundaries, and do not introduce shell execution, test/lint execution,
merge, push, PR creation, or automatic cleanup.

`/files` remains available as manual/debug context loading. It is no longer the
normal human-facing workflow and should not be presented as the recommended TUI
path.

Setting `/task` invalidates previous discovery. `/reset` clears task, manual
context, discovery state, latest routing/result, and skipped/rejected context
state while preserving the selected workspace.

## Standby Experimental And Compatibility Path

The SFE proxy and Dockerized proxy path are in standby for the current TUI V0.1
user-facing work. They remain useful infrastructure for:

- OpenAI-compatible traffic compatibility;
- safe observability in `shadow` mode;
- controlled `dry_run_enabled` and `enabled` experiments;
- CodexCLI stress tests;
- `/v1/responses` request-shape and streaming experiments;
- provider integration probes.

The proxy is not the canonical SFE user interface. CodexCLI through the proxy is
useful for compatibility and stress testing, but realistic CodexCLI traffic can
embed large or protected context inside client-specific request envelopes. SFE
should not depend on reverse-engineering that traffic shape as its primary
interface.

Dockerized proxy operation is also standby infrastructure, not the recommended
current user path.

Provider selection is shared across SFE surfaces through `SFE_PROVIDER`.
Standby proxy compatibility still accepts `SFE_PROXY_PROVIDER` as a legacy
fallback, but new configuration should use `SFE_PROVIDER`.

`ProxyBackend` may remain in the TUI codebase as an internal experimental stub,
but it must not be exposed as a user-facing backend yet. The TUI should not
offer backend switching until a concrete need is proven.

Historical proxy milestone and mode notes remain useful audit records under
`docs/history/proxy/`, but they should be read as standby experimental smoke
and controlled-run history. They do not establish production reliability,
general token savings, or broad provider behavior.

## What Remains Unproven

Before making practical value claims, SFE still needs evidence that the
canonical TUI path can repeatedly deliver useful context reduction without
hurting task correctness.

The minimum proof still missing includes:

- repeated TUI runs on realistic tasks, not only unit tests or anecdotes;
- strict success criteria that do not count fallback, repair, or hidden full
  context substitution as success;
- measured selected-context quality, token reduction, latency, and provider
  cost;
- failure reporting for no-match routing, over-selection, under-selection, and
  provider errors;
- repeated evidence for the router-reviewed write and worktree flows beyond
  unit tests and manual validation;
- stronger evidence for real Responses streaming context replacement before it
  is treated as generally usable;
- clearer operational guidance for secrets, logs, provider limits, and local
  proxy exposure.

The current status is therefore: TUI plus `DirectBackend` is the primary
architecture direction; proxy work is standby experimental compatibility and
research infrastructure; practical value remains to be demonstrated with
controlled, repeatable workflows.
