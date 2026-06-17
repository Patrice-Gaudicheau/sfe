# TUI Apply Patch Legacy Design

Status note: this is a historical TUI design note from the legacy `/patch` and
`/apply-patch` era. It predates the current `/run`-first workflow and the
Aider-backed workspace writer default. It is preserved for safety-boundary
lessons and should not be read as the primary current write path.

## Historical Purpose

The legacy flow split proposal from mutation:

- `/patch` asked the configured executor/provider for a structured edit
  proposal, rendered a local preview, and wrote nothing.
- `/apply-patch` was the explicit write boundary. It asked a router reviewer
  whether the pending proposal matched the original task, then applied the
  structured replacements only after approval and mechanical path checks.

This protected the TUI from provider-controlled direct writes during that phase
of the project.

## Proposal Shape

The internal proposal was file-content based:

- `replace_existing_file` for existing text files;
- `create_file` for absent text files.

Deletes, renames, mode changes, symlink changes, binary writes, and legacy
diff-only proposals were unsupported. Provider-supplied diff text was treated
as diagnostic only; SFE computed the trusted readable diff locally from current
file content and proposed full replacement content.

## Review And Guards

Before writing, the router reviewer received the original task, selected and
discovery metadata, touched paths, readable current contents, proposed
replacement contents, the SFE-computed diff, allowed paths, and obvious task
constraints.

The router returned either `OK_APPLY` or `KO_BLOCK`. Router review was semantic
and task-oriented; it did not repair proposals.

Python kept the mechanical boundary:

- reject missing pending proposals;
- reject absolute paths and workspace escapes;
- never run shell commands or subprocesses;
- never write before explicit `/apply-patch`;
- write all approved replacements as all-or-nothing.

## Diagnostic Lessons

Success and failure reports were intended to expose safe metadata only: status,
router decision, provider/model labels, modified relative paths, file count, and
whether pending work was cleared. They were not allowed to render raw file
contents, replacement contents, provider payloads, request bodies,
authorization headers, API keys, `.env` values, or absolute workspace paths.

## Current Interpretation

The useful historical lessons are still relevant:

- proposal and mutation boundaries should be explicit;
- provider-supplied diffs are not the source of truth for writes;
- local path/workspace guards are separate from semantic review;
- diagnostics should be safe and compact.

The current primary workflow is `/task <request>` followed by `/run`. When
`workspace_write` is selected, SFE uses the configured workspace writer,
defaulting to Aider-backed filesystem execution, with SFE-owned isolation,
validation, promotion, reporting, and bounded Real Loop behavior where
supported.
