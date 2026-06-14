# Aider Filesystem Executor Integration

This note describes the target architecture for making Aider the normal
filesystem writer for SFE `workspace_write` execution. The current branch has
the Aider-backed single-pass and multi-pass `workspace_write` paths
implemented. The legacy text transport remains available only through the
explicit `SFE_WORKSPACE_WRITE_EXECUTOR=text` fallback.

## Target Architecture

The target `workspace_write` flow is:

1. SFE routes the task through the existing execution-mode router.
2. SFE prepares the selected workspace as a Git repository when needed.
3. SFE creates or reuses an SFE-controlled Git worktree.
4. SFE discovers and selects bounded context.
5. SFE optionally plans work into small multi-pass batches.
6. SFE invokes Aider inside the active SFE worktree only.
7. Aider writes files on disk, and may create commits inside that worktree.
8. SFE captures the resulting worktree changes as the source of truth.
9. SFE validates target-directory boundaries and blocked internal paths.
10. SFE reports, promotes, and records diagnostics through the existing TUI and
    MCP result surfaces.

The important inversion is that generated disk state becomes the execution
artifact. Provider text is no longer the primary file transport for normal
large multi-file generation.

## Why Aider Is Mandatory But Not Vendored

Aider should be mandatory for normal filesystem execution because SFE's current
large-file weakness is not routing or planning; it is reliable conversion of
LLM text into many files. Aider already owns the filesystem-writing agent loop,
file edits, and local Git-aware workflow. SFE should delegate that responsibility
instead of continuing to grow text parsing and patch repair behavior.

Aider must not be vendored into this repository. Keeping it external:

- avoids copying a fast-moving agent project into SFE;
- keeps Aider upgrades and security fixes on Aider's normal release path;
- keeps SFE focused on routing, context selection, validation, reporting, and
  promotion;
- avoids mixing Aider source, dependencies, and license/update concerns with
  SFE's own codebase.

If Aider is missing, normal filesystem execution should fail closed with clear
installation instructions. On Ubuntu, Debian, and WSL, prefer `pipx`; direct
`pip` installation into the system Python can fail in externally managed Python
environments because of PEP 668:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
exec $SHELL -l
pipx install aider-chat
aider --version
which aider
```

`which aider` may resolve to a user-local executable such as
`~/.local/bin/aider`; that is a valid installation as long as it is on `PATH`.

The older `aider-install` bootstrap remains an alternative installation method:

```bash
python -m pip install aider-install
aider-install
```

The final implementation should detect the executable before starting a
`workspace_write` run that requires filesystem execution, return a structured
issue, and render the same guidance in TUI and MCP outputs.

## Why Git Worktrees Remain Necessary

SFE-controlled worktrees remain the primary safety boundary. Aider must never
run directly in the user's source checkout. It may only run with its current
working directory set to the active SFE worktree, or to the selected target
subdirectory inside that worktree when SFE has selected a subdirectory.

Worktrees still provide:

- isolation from the user source branch while generation is in progress;
- a Git-owned place where Aider can create commits without mutating the source
  checkout;
- a stable diff and status surface for SFE validation and reporting;
- metadata that lets SFE clean only sessions it created;
- a mechanical boundary for promotion back to the selected destination.

The current `GitWorktreeBackend` already creates `sfe/worktree/<id>` branches
under `.sfe-worktrees`, records SFE session metadata, refuses dirty source repos
by default, and ignores non-SFE worktrees during cleanup. The Aider integration
should preserve those properties.

## Conceptual Aider Invocation

The implementation should introduce a core-owned Aider filesystem executor
rather than embedding Aider calls in the TUI or MCP layers.

Conceptually, SFE should invoke Aider with:

- `cwd` set to the active SFE worktree or active destination path inside it;
- a bounded task message generated from the SFE task, selected context summary,
  and batch goal when multi-pass is active;
- explicit file paths for files Aider is expected to create or edit whenever
  SFE knows them;
- a small selected context set, not the whole repository;
- non-interactive execution suitable for TUI and MCP;
- diagnostics capture for command, working directory, return code, stdout/stderr
  lengths, provider/model metadata when available, and elapsed time.

The exact CLI flags should be verified during implementation against the
installed Aider version. The architecture should not depend on undocumented
flags if a stable alternative exists.

## Context Control Policy

SFE remains the context router. Aider must not receive the full repository or
an oversized global context by default. For single-pass `workspace_write`, SFE
should give Aider:

- a short scoped instruction;
- explicit editable paths when SFE knows them;
- explicit new file paths when SFE can infer them;
- only selected supporting files via read-only context paths.

Aider must not become a second global planner competing with SFE. For later
multi-pass work, each Aider invocation should be batch-specific, small, and
bounded by the Router-owned plan.

## Non-Interactive Invocation Policy

Aider is invoked as a one-shot, non-interactive filesystem writer. Local Aider
0.86.2 supports the required flags: `--message-file`, `--env-file`,
`--yes-always`, `--no-pretty`, `--no-stream`, `--no-gui`, `--no-browser`,
`--git`, `--no-gitignore`, `--no-add-gitignore-files`, `--auto-commits`,
`--no-auto-lint`, `--no-auto-test`, `--subtree-only`, `--map-tokens`,
`--model`, `--weak-model`, and `--timeout`.

The executor should:

- send the task through a temporary message file rather than command-line text;
- pass only a minimal temporary Aider env file;
- place Aider input/chat history files outside the worktree and delete them
  after execution;
- avoid Aider-created `.gitignore` and repo-map cache churn in the worktree;
- close stdin so the process cannot wait for terminal input;
- capture stdout and stderr with bounded diagnostics;
- pass `--timeout` when `SFE_AIDER_TIMEOUT_SECONDS` is configured;
- apply the same configured timeout to the spawned Aider process;
- fail with a structured timeout or execution error rather than blocking
  indefinitely.

## Aider Model Selection Policy

`SFE_AIDER_MODEL` is the highest-priority explicit override for Aider. When it
is unset, SFE resolves the executor provider from `SFE_PROVIDER_EXECUTOR`, then
`SFE_PROVIDER`, then the default `openai`, and only then selects the known-safe
executor model for that provider.

The Aider fallback model must come from executor settings, not router settings:

- `openai` uses `SFE_OPENAI_EXECUTOR_MODEL`;
- `anthropic` uses `SFE_ANTHROPIC_EXECUTOR_MODEL`;
- `google` uses `SFE_GOOGLE_MODEL` in the current configuration model;
- OpenAI-compatible or local providers such as Alibaba/Qwen, Lemonade, and
  Ollama require `SFE_AIDER_MODEL` unless a tested Aider/LiteLLM-compatible
  mapping exists.

SFE must never fall back to `SFE_PROVIDER_ROUTER` or router model settings for
Aider. Router models are chosen for planning and routing, may be more
expensive, and are not the filesystem execution default. If no safe Aider model
can be selected, the run fails closed with `missing_aider_model`.

Before spawning Aider, SFE must assert:

- the active workspace path is inside the SFE worktree;
- the process working directory is not the original source checkout;
- every explicit path passed to Aider is relative, normalized, and inside the
  selected destination;
- blocked internal paths such as `.git` and `.sfe-worktrees` are not selected;
- a missing Aider executable produces the installation guidance above.

## SFE Responsibilities

SFE remains responsible for:

- execution-mode routing;
- target directory resolution;
- Git preparation and SFE worktree creation;
- discovery and context selection;
- optional multi-pass planning;
- choosing expected or allowed files for each Aider call;
- keeping Aider context small and task batches bite-sized;
- validating that actual changed paths stay inside the selected destination;
- blocking internal paths and unsafe traversal;
- reporting progress and diagnostics;
- promoting accepted changes from the worktree to the selected source
  destination;
- preserving TUI/MCP runtime equivalence;
- retaining legacy text transport only as an explicit fallback or compatibility
  path.

SFE should not ask Aider to decide the global SFE plan. The Router can still
plan the work, and Aider executes a scoped filesystem step.

## Aider Responsibilities

Aider becomes responsible for:

- translating the SFE task or batch goal into concrete file edits;
- creating, modifying, and deleting files on disk inside the SFE worktree;
- using its own edit loop rather than returning `SFE_FILE` blocks;
- managing its own internal context and model/tool interactions;
- creating commits inside the SFE worktree when its configured workflow does so.

Aider must not be responsible for promotion into the user source directory, SFE
session cleanup, target-boundary policy, or final SFE reporting.

## Commit Promotion Policy

Aider may create micro-commits inside the SFE-controlled worktree. Those commits
are treated as session execution history only. SFE does not promote Aider
commits directly into the user source checkout.

The effective policy is squash-at-promotion:

- SFE captures committed changes relative to the session source head and
  uncommitted worktree changes;
- SFE validates the final changed paths and file state against the selected
  destination boundary and internal path blocklist;
- SFE promotes only validated destination-bound file changes;
- user-facing source history receives the final promoted state, not Aider's
  internal micro-commit sequence.

## TUI Impact

On this branch, the intended TUI default is:

```text
/task <request>
/run
```

When the execution-mode router selects `workspace_write`, `/run` uses the
Aider-backed filesystem executor by default. The TUI should surface:

- the same compact progress events already used by `RunPipeline`;
- an explicit missing-Aider failure with the install commands;
- promoted files and worktree metadata from the existing run result shape;
- Aider diagnostics only in bounded, secret-safe debug/report output.

Legacy commands such as `/patch`, `/apply-patch`, `/auto-patch`, and direct
text proposal flows can remain available for debugging and compatibility, but
they should not be presented as the preferred large multi-file path.

## MCP Impact

MCP should inherit the same behavior through `RuntimeSession.run()` and
`RunPipeline`; it should not gain an MCP-specific Aider implementation.

`sfe_run` should use the Aider-backed filesystem executor whenever the shared
runtime would do so for TUI `/run`. `sfe_run_report` should expose safe
structured diagnostics for the Aider execution. Missing Aider should return a
structured failed run with the same installation guidance rather than silently
falling back to text transport.

This preserves the existing TUI/MCP ISO requirement: one shared runtime path,
different renderers.

## Legacy And Fallback Behavior

`SFE_FILE` blocks, structured replacement JSON, and strict Git diffs should
become legacy text transports. They remain useful for:

- deterministic tests;
- providers or environments that explicitly opt into text-only compatibility;
- debugging the old parser path;
- small controlled cases where direct filesystem execution is not desired.

They should not remain the preferred path for large multi-file generation once
the Aider executor is enabled by default. Missing Aider does not silently fall
back for normal `workspace_write`; it fails closed with installation
instructions.

## Current Code Touchpoints

The relevant current implementation areas are:

- `sfe/run_pipeline.py`: top-level `/run` pipeline, worktree creation, text
  response parsing, direct filesystem mutation capture, boundary validation,
  promotion, and multi-pass execution.
- `sfe/runtime_session.py`: shared TUI/MCP runtime controller that delegates to
  `RunPipeline`.
- `sfe/execution_backend.py`: current execution backend protocol.
- `sfe_tui/backends.py`: `DirectBackend` dry-run, patch, and multi-pass adapter.
- `sfe_tui/executors.py`: provider-backed text executor and
  `WORKSPACE_WRITE_TEXT_TRANSPORT_INSTRUCTION`.
- `sfe/workspace_write_transport.py`: `SFE_FILE` text transport contract.
- `sfe/multipass.py` and `sfe/multipass_planner.py`: multi-pass configuration,
  validation, and Router-owned batch planning.
- `sfe/workspace_isolation.py` and `sfe/git_worktree_backend.py`: worktree
  abstraction, SFE session metadata, status, cleanup, and GC.
- `sfe_mcp/tools.py` and `sfe_mcp/serializers.py`: MCP handlers and safe
  structured result output.
- `tests/test_sfe_run_pipeline.py`: existing evidence that direct worktree
  mutations can be promoted when they remain inside the destination boundary.
- `tests/test_sfe_mcp_tools.py`: MCP uses the shared runtime and current
  `SFE_FILE` transport.

## Risks And Open Questions

- Aider context can grow too large if SFE passes broad context. SFE must keep
  selected context small and prefer explicit edit/read paths.
- Aider CLI flags and installation shape need implementation-time verification.
  The design should depend on stable commands and detect version/capability
  problems clearly.
- Aider has its own context strategy. SFE must avoid overloading it with too
  many files while still giving enough selected context and explicit target
  paths.
- Aider's own commits need a reporting policy. SFE should decide whether to
  preserve commit metadata in diagnostics, squash at promotion time, or ignore
  commit boundaries and promote file state only.
- Current multi-pass `allowed_files` are warnings rather than hard rejection
  when extra in-destination files change. The current Aider path preserves that
  warning-oriented policy; a later hard-scope mode would need a separate design.
- Long-running Aider calls need cancellation and richer progress behavior that
  is acceptable for both TUI and MCP; the current Aider paths use
  non-interactive execution and configured timeout handling.
- Secret handling needs care. SFE should not echo full prompts, file contents,
  environment variables, or Aider logs that may contain secrets in normal MCP
  or TUI output.
- Cross-platform path handling matters because local users may launch SFE from
  Windows clients into WSL. Aider should receive WSL-native paths when SFE runs
  inside WSL.
- Binary files, generated dependency directories, deletes, renames, and symlink
  behavior need explicit validation coverage.

## Phased Implementation Plan

### Phase 0: Documentation And Design Boundary

- Add this design note.
- Keep runtime behavior unchanged.
- Confirm the current direct-mutation promotion tests and worktree behavior.

### Phase 1: Aider Preflight And Diagnostics

- Add a small core preflight helper that detects Aider.
- Return a structured missing-Aider issue with the exact installation commands.
- Add unit tests for missing executable diagnostics.
- Do not route normal `/run` to Aider yet.

### Phase 2: Filesystem Executor Interface

- Introduce a core filesystem executor boundary separate from text response
  parsing.
- Model the result as disk mutation plus bounded diagnostics, not as a patch
  string.
- Keep `ExecutionBackend.patch()` text behavior intact as the legacy path.
- Add a fake filesystem executor for tests.

### Phase 3: Promotion Capture For Committed Worktree Changes

- Extend promotion baseline capture to detect changes relative to the SFE
  session source head, including Aider-created commits.
- Combine committed branch diffs with uncommitted worktree status.
- Preserve existing destination-boundary checks before promotion.
- Add tests where the executor commits inside the worktree and SFE still
  promotes only valid destination paths.

### Phase 4: Single-Pass Aider Workspace Write

- Add the default Aider-backed `workspace_write` path for single-pass runs.
- Invoke Aider only inside the active SFE worktree.
- Capture actual disk changes, validate boundaries, promote, and report.
- Verify missing-Aider failure behavior in both TUI and MCP tests.

### Phase 5: Multi-Pass Aider Execution

- Reuse the Router-owned multi-pass plan.
- For each batch, call Aider with the batch goal, explicit expected files, and
  minimal selected context.
- Capture and promote each pass, then refresh context for later passes.
- Report per-pass diagnostics and warnings consistently with current
  `MultiPassRunSummary`.

### Phase 6: Make Aider The Default Filesystem Writer

- Normal TUI `/run` and MCP `sfe_run` `workspace_write` execution use the
  Aider-backed path by default on this branch.
- Missing Aider fails closed.
- Text transport remains behind an explicit legacy/fallback configuration.
- User docs and `.env.example` should continue to reflect the branch default.

### Phase 7: Legacy Cleanup

- Keep the old text parser path long enough for tests, compatibility, and
  rollback.
- Deprecate `SFE_FILE` as the preferred large generation path.
- Remove or simplify repair-oriented code only after the Aider path has enough
  live validation.

## Feasibility Assessment

The integration appears feasible because SFE already has most of the required
outer shell: execution-mode routing, discovery, multi-pass planning, worktree
creation, direct filesystem mutation capture, boundary validation, promotion,
and shared TUI/MCP runtime plumbing.

The main required runtime change is replacing text-response parsing as the
normal writer with a filesystem executor that invokes Aider. The main safety
change is expanding promotion capture from uncommitted worktree status to the
full worktree branch delta so Aider-managed commits are visible to SFE before
promotion.
