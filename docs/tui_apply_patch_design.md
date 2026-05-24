# TUI Apply Patch Design

This note defines the safety boundary for the first-party SFE TUI
`/patch` -> `/apply-patch` workflow.

## Purpose

`/patch` asks the configured executor/provider for a structured edit proposal.
It renders the proposal as proposal-only output and never writes files, runs
shell commands, calls git, executes tools, or applies anything.

`/apply-patch` is the separate explicit write boundary. It asks the configured
router reviewer whether the pending proposal is globally acceptable for the
original task. Python keeps only mechanical guards and the physical write
mechanism.

## Pending Proposal Format

The internal pending proposal is file-replacement based, not unified-diff
based:

```json
{
  "edits": [
    {
      "path": "src/package/module.py",
      "action": "replace_existing_file",
      "content": "full replacement file content\n"
    }
  ],
  "diff_preview": "optional unified diff for display"
}
```

For now, only `replace_existing_file` is supported. Creates, deletes, renames,
mode changes, symlink changes, and binary writes are unsupported edit formats.
Unified diffs may be displayed as previews, but they are not the internal source
of truth for application.

Legacy diff-only pending proposals are not applied. They should be reported as
`unsupported_pending_patch_format` unless full replacement content is available
through the structured format.

## Router Review

Before any write, `/apply-patch` sends the configured router reviewer:

- the original user task;
- selected context metadata;
- discovery metadata;
- touched workspace-relative paths;
- current contents of touched files when readable;
- proposed full replacement contents;
- allowed workspace-relative paths;
- inferred task constraints when obvious, such as `existing_files_only`.

The router returns a structured decision:

```json
{
  "decision": "OK_APPLY",
  "reason": "The proposal matches the task and stays within selected files.",
  "files_reviewed": ["src/package/module.py"],
  "risk_level": "low"
}
```

The only valid decisions are `OK_APPLY` and `KO_BLOCK`.

## Mechanical Guards

Python does not decide whether the patch is semantically correct for the task.
It keeps only these mechanical guards:

- reject `/apply-patch` when there is no pending proposal;
- reject absolute paths;
- reject paths that escape the selected workspace;
- never run shell commands or subprocesses;
- never write before explicit `/apply-patch`;
- write all approved replacements as an all-or-nothing operation.

Python does not reject hidden files, suffixes, binary-looking paths, or
secret-looking paths as semantic policy. Unsupported non-text replacement data
is reported as `unsupported_edit_format` because the current structured format
stores text content only.

## Command Semantics

`/patch`:

- calls the configured executor/provider for a structured replacement proposal;
- stores a pending proposal only when structured replacement content is present;
- may render a readable diff preview;
- never writes files.

`/apply-patch`:

- fails clearly with `no_pending_patch` if no proposal is pending;
- runs mechanical path guards before router review;
- calls the configured router reviewer;
- if the router returns `KO_BLOCK`, writes nothing and keeps the pending
  proposal;
- if the router returns `OK_APPLY`, writes the proposed full replacement
  contents;
- clears the pending proposal only after successful writes;
- if physical writing fails, writes nothing, reports `physical_write_failure`,
  and keeps the pending proposal.

## Diagnostics

Apply success should render safe metadata only:

```text
SFE apply-patch
  status: applied
  router decision: OK_APPLY
  router provider: openai
  router model: ...
  modified relative paths: path/a.py, path/b.md
  file count: 2
  pending patch cleared: yes
```

Router rejection should be distinct from physical write failure:

```text
SFE apply-patch
  status: failed
  error category: router_rejected_patch
  failure kind: router_rejected
  router decision: KO_BLOCK
  pending patch cleared: no
  no files were modified
```

```text
SFE apply-patch
  status: failed
  error category: physical_write_failure
  failure kind: physical_write_failure
  router decision: OK_APPLY
  pending patch cleared: no
  no files were modified
```

Diagnostics must not render raw file contents, full replacement contents,
request bodies, provider payloads, authorization headers, API keys, `.env`
values, or absolute workspace paths.

## Test Plan

Use `tmp_path` only. Do not call real providers. Do not run shell commands
inside the TUI.

Required focused tests:

- `/patch` stores a structured replacement proposal;
- `/patch` performs no writes;
- `/patch` renders a readable preview when available;
- `/apply-patch` with `OK_APPLY` writes full file contents;
- `/apply-patch` with `KO_BLOCK` writes nothing and keeps pending;
- successful apply clears pending only after the write succeeds;
- physical write failure keeps pending and writes nothing;
- multi-file physical write failure rolls back prior writes;
- absolute paths are rejected before router review;
- workspace escapes are rejected before router review;
- no pending proposal reports `no_pending_patch`;
- no shell command is used;
- legacy diff-only proposals are not routed through hunk/preimage application.
