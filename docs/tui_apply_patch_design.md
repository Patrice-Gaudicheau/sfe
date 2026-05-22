# TUI Apply Patch Design

This note defines the safety boundary for the first-party SFE TUI
`/apply-patch` command. V0 implements the narrow local-only behavior described
here; this document remains the boundary for what that implementation is and is
not expected to support.

## Purpose

`/patch` asks the configured read-only executor for a patch proposal and
renders it as proposal-only output. It does not write files, run shell
commands, execute tools, call git, or apply anything.

`/apply-patch` provides a separate, explicit, local-only
write boundary for applying a narrow subset of safe patch proposals inside the
selected workspace.

The intended workflow would be:

```text
/task <question>
/discover
/dry-run
/patch
/apply-patch
```

`/patch` must remain proposal-only. `/apply-patch` must never run
automatically after `/patch`.

## Non-Goals

V0 should not support:

- shell execution;
- `git apply` or any subprocess;
- tool execution;
- provider calls during `/apply-patch`;
- backend switching;
- `ProxyBackend` exposure;
- writes outside the selected workspace;
- writes to secret-like, local-only, generated, binary, or oversized files;
- applying arbitrary prose explanations;
- applying markdown-fenced text unless the contained diff can be safely
  extracted by an explicitly designed parser;
- new files, deleted files, renames, chmod changes, symlinks, submodules, or
  binary patches;
- automatic apply after provider output;
- broad claims of robust patching.

## Safety Boundary

`/apply-patch` should be treated as the first write-capable TUI boundary. It
should be intentionally narrower than common patch tools.

Hard constraints:

- no shell commands;
- no subprocesses;
- no git commands;
- no provider calls;
- no backend switching;
- no proxy use;
- no writes outside the selected workspace;
- no writes to `.env`, `.env.*`, `.ssh`, hidden directories, caches, logs,
  local databases, generated artifacts, binary files, non-UTF-8 files, or files
  above the configured size limit;
- no raw secrets in diagnostics;
- compact metadata-only diagnostics.

The command should use the same general safety vocabulary already present in
`sfe_tui.contracts` and `sfe.discovery`: workspace-relative refs, UTF-8 text
checks, binary rejection, secret-like path rejection, and size limits.

## Command Semantics

`/apply-patch` should apply only the latest pending patch proposal stored by a
successful `/patch` command.

If there is no pending patch proposal:

```text
Error: no_pending_patch - run /patch first
```

If the pending proposal is not an accepted unified diff:

```text
Error: invalid_patch_proposal - latest patch proposal is not an applyable unified diff
```

If the patch is dangerous or unsupported:

```text
Error: unsafe_patch - patch touches unsupported or unsafe paths
```

If the patch preimage does not match disk:

```text
Error: patch_preimage_mismatch - file changed or patch does not match current content
```

On success, render only safe metadata:

- applied: yes;
- modified relative paths;
- file count;
- hunk count;
- lines added/removed;
- pending patch cleared: yes.

Do not render full file contents or full diff content in the apply result.

## Patch Proposal Lifecycle

The TUI should add explicit pending patch state, for example:

```python
@dataclass(frozen=True)
class PendingPatchProposal:
    text: str
    source: str
    created_from_task_hash: str
    selected_source_refs: tuple[str, ...]
    provider_name: str | None
    hunk_count: int | None = None
    file_count: int | None = None
    parse_status: str | None = None
```

The raw proposal text is internal session state. It should not be printed in
status or apply diagnostics.

Store pending patch state only after `/patch` returns an answer that looks like
a unified diff and passes the parser's initial validation. If `/patch` returns
a non-diff explanation, render the explanation as today but do not create a
pending patch.

Invalidation rules:

- `/reset` clears pending patch state.
- `/task` clears pending patch state.
- `/discover` clears pending patch state.
- `/ask` clears pending patch state because it changes the latest executor
  outcome away from patch proposal context.
- `/patch` replaces pending patch state on a valid diff proposal and clears it
  on provider failure or non-diff output.
- Manual `/files` should clear pending patch state because active context
  changed.

`latest_result` can continue to track the latest backend result. Pending patch
state should be separate from `latest_result` so an answer and a patch proposal
cannot be confused.

## Distinguishing Answers From Patch Proposals

Do not infer applyability from `BackendResult.answer` alone. A normal `/ask`
answer may contain code or diff-like text. Only `/patch` may create a pending
patch proposal, and only after the proposal passes unified diff parsing.

Recommended distinction:

- `/ask` result: never applyable.
- `/patch` result with no answer: no pending patch.
- `/patch` result with prose/non-diff answer: no pending patch.
- `/patch` result with one valid unified diff touching supported files:
  pending patch available.

Status can report `pending patch: yes/no`, `pending patch files: N`, and
`pending patch hunks: N`, but should not print raw diff text.

## Unified Diff Parsing Policy

V0 should accept only a conservative unified diff subset:

```text
diff --git a/path b/path
--- a/path
+++ b/path
@@ -old_start,old_count +new_start,new_count @@ optional heading
 context
-removed
+added
```

Parsing should be implemented in pure Python. The parser should produce a
structured model such as:

```python
@dataclass(frozen=True)
class ParsedPatch:
    files: tuple[ParsedFilePatch, ...]

@dataclass(frozen=True)
class ParsedFilePatch:
    old_path: str
    new_path: str
    hunks: tuple[ParsedHunk, ...]

@dataclass(frozen=True)
class ParsedHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[PatchLine, ...]
```

Reject:

- missing `diff --git`, `---`, or `+++` headers;
- `--- /dev/null` or `+++ /dev/null`;
- `new file mode`;
- `deleted file mode`;
- `rename from`;
- `rename to`;
- `similarity index`;
- `old mode`;
- `new mode`;
- `Binary files ... differ`;
- `GIT binary patch`;
- paths that differ between `diff --git`, `---`, and `+++`;
- paths without the `a/` and `b/` prefixes;
- absolute paths;
- `..` traversal;
- empty paths;
- malformed hunk ranges;
- hunks with impossible line accounting.

Non-diff explanations should be rejected for apply while still allowed as
proposal-only `/patch` output.

## File And Path Validation Policy

Every touched path must be a workspace-relative path after stripping `a/` or
`b/` prefixes. The resolved path must remain inside `workspace_root`.

Reject paths when:

- the original path is absolute;
- the path contains `..`;
- the path is empty;
- any path component is hidden, except explicitly allowed public examples if a
  later design chooses to allow them;
- any component is `.git`, `.hg`, `.svn`, `.ssh`, cache directories, `logs`,
  `build`, `dist`, `node_modules`, `.venv`, or `venv`;
- the basename is `.env` or starts with `.env.`;
- the basename is a private-key-like filename;
- the suffix is a local DB, log, JSONL stream, binary archive, compiled file, or
  unsupported generated artifact;
- the target is not an existing regular file;
- the target is a symlink;
- the current file is above the configured size limit;
- the current file is binary or non-UTF-8;
- the current file is secret-like according to existing TUI context loading
  rules.

V0 can reuse or extract shared validation ideas from `sfe.discovery` and
`sfe_tui.contracts`, but should avoid a large refactor unless needed.

## Apply Algorithm Options

### Option A: Pure Python Deterministic Applier

Implement a tiny unified diff applier for the accepted V0 subset.

Pros:

- no subprocess;
- no shell;
- no dependency;
- deterministic;
- easy to constrain and test;
- matches the narrow safety goal.

Cons:

- easy to get wrong if the accepted diff subset grows;
- needs careful hunk accounting tests.

### Option B: Third-Party Patch Library

Use a dependency for parsing/applying diffs.

Pros:

- may handle more diff shapes.

Cons:

- larger trust surface;
- harder to constrain;
- may support features V0 should reject;
- adds dependency management and audit burden.

Recommendation: use Option A for V0. Keep the accepted format intentionally
small and deterministic.

## Preimage Validation

Before writing, `/apply-patch` must validate the patch preimage against the
current file content.

Recommended algorithm:

1. Read the target file as bytes.
2. Reject if size is above the limit.
3. Reject if binary or non-UTF-8.
4. Decode as UTF-8 and preserve line endings conservatively.
5. For each hunk, check every context and removed line against the current
   file at the expected location.
6. If any context or removed line does not match, abort the entire apply.
7. Build all new file contents in memory first.
8. Only after every file and hunk validates, write modified files.

V0 should apply atomically at the logical level: no file should be written if
any file/hunk fails validation. It does not need OS-level atomic replacement in
the first implementation, but writing via a temporary file and `Path.replace`
can be considered after the core algorithm is tested.

## Failure Behavior

If the patch does not apply cleanly, `/apply-patch` should:

- write nothing;
- keep pending patch state available when the failure is a preimage mismatch;
- clear pending patch state when the failure is invalid/dangerous, because the
  proposal should not be retried;
- render only reason categories and relative paths, not file contents.

Examples:

- `patch_preimage_mismatch`: keep pending patch.
- `unsafe_patch`: clear pending patch.
- `unsupported_patch_feature`: clear pending patch.
- `read_error`: keep pending patch unless the path is unsafe.
- `write_error`: keep pending patch and report safely.

## V0 Scope Recommendation

Smallest safe V0:

- `/patch` remains proposal-only.
- `/patch` stores a pending patch only when the provider output is a valid
  unified diff in the accepted subset.
- `/apply-patch` applies only the latest pending patch.
- Existing UTF-8 text file modifications only.
- No new files.
- No deletions.
- No renames.
- No chmod/mode changes.
- No binary patches.
- No symlinks.
- No hidden/secret/generated/local paths.
- Pure Python parser and applier.
- Full preimage validation before any write.
- Safe summary after apply.
- Pending patch cleared after successful apply.
- Pending patch retained after clean preimage mismatch.
- Pending patch cleared after invalid/dangerous proposal detection.

Do not create backups in V0. Backups add another write surface and naming
policy. The safer first implementation is all-or-nothing validation before
writing and a clear summary of modified relative paths. Users who need recovery
can rely on their VCS or editor history outside the TUI.

The command itself is the explicit confirmation for V0. Do not add implicit
apply. A separate `/patch-status` command is useful but not required for the
smallest safe V0 if `/status` reports compact pending patch metadata. If added,
`/patch-status` should show only safe metadata: files, hunks, added/removed
line counts, parse status, and why apply is or is not available.

## Diagnostics After Apply

Render:

```text
SFE apply patch
  applied: yes
  modified files: path/a.py, path/b.md
  file count: 2
  hunk count: 3
  added lines: 12
  removed lines: 8
  provider calls made: 0
  shell enabled: no
  tool execution enabled: no
  pending patch cleared: yes
```

On failure:

```text
SFE apply patch failed
  reason: patch_preimage_mismatch
  affected files: path/a.py
  files written: 0
  provider calls made: 0
  shell enabled: no
  tool execution enabled: no
  pending patch retained: yes
```

Do not render raw hunks, removed lines, added lines, request bodies, provider
payloads, authorization headers, API keys, `.env` values, or absolute paths.

## Test Plan

Use `tmp_path` only. Do not call providers. Do not use shell commands inside
the TUI. Do not write outside the temporary workspace.

Parser tests:

- accepts one-file unified diff modification;
- accepts multiple hunks in one existing file;
- accepts multiple existing files;
- rejects non-diff prose;
- rejects markdown-only explanations;
- rejects malformed headers;
- rejects `/dev/null`;
- rejects new file patches;
- rejects delete patches;
- rejects rename patches;
- rejects chmod/mode changes;
- rejects binary patches;
- rejects absolute and traversal paths;
- rejects hidden, `.env`, `.ssh`, cache, log, DB, JSONL, generated, binary, and
  oversized paths.

Apply tests:

- applies a simple modification to an existing UTF-8 file;
- applies multiple hunks after validating all preimages;
- writes nothing when one hunk mismatches;
- writes nothing when one file is unsafe;
- writes nothing when a target is a symlink;
- writes nothing when one file is binary/non-UTF-8;
- clears pending patch after success;
- keeps pending patch after preimage mismatch;
- clears pending patch after dangerous proposal;
- `/reset`, `/task`, `/discover`, `/ask`, `/files`, and failed `/patch`
  invalidate pending patch according to policy;
- `/apply-patch` makes zero provider calls;
- diagnostics contain only relative paths and counts;
- diagnostics do not contain raw file content, removed secrets, env values,
  request bodies, authorization headers, or absolute workspace paths.

Integration-style TUI tests:

- `/apply-patch` before `/patch` reports `no_pending_patch`;
- `/patch` with non-diff answer does not create pending patch;
- `/patch` with diff answer creates pending patch metadata;
- `/status` reports pending patch metadata safely;
- `/apply-patch` succeeds on a simple safe diff;
- `/apply-patch` failure leaves workspace unchanged.

## Implementation Sequence

1. Add dataclasses for pending patch and parsed patch structures.
2. Add a pure Python unified diff parser for the accepted V0 subset, with
   parser tests before any file writes are introduced.
3. Add path and file validation helpers, initially local to the TUI patch
   module to avoid premature core refactors, with validator tests for unsafe
   paths and file types.
4. Add an in-memory applier that validates all hunks before writing, with
   applier tests for success, preimage mismatch, and no partial writes.
5. Add pending patch state to `SfeTuiApp`.
6. Update `/patch` to create pending patch metadata only for valid diffs.
7. Add `/apply-patch` command that uses pending patch state and performs zero
   provider calls.
8. Add safe renderer functions for pending status and apply results.
9. Add focused parser, applier, and TUI tests.
10. Update docs after behavior lands.

## Open Questions

- Should `/patch-status` be added in V0, or is `/status` pending patch metadata
  enough?
- Should markdown fenced diffs be accepted if the enclosed body is a clean
  unified diff, or should V0 require raw unified diff only?
- Should V0 allow `.env.example`, or reject all hidden-path-like files for
  simpler safety?
- Should the applier preserve original line-ending style exactly, or normalize
  to the decoded text representation in V0?
- Should successful apply use temporary-file replacement immediately, or can
  direct writes wait until after the in-memory all-or-nothing validation?
- Should pending patch invalidation be tied to a hash of selected context and
  task, or is command-based invalidation sufficient for V0?
- Should future versions support new files behind a separate explicit flag or
  command?
