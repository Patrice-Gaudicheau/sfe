# SFE Continuity And Orientation Glossary

Status note: this is historical/speculative vocabulary. It predates the
current `/run`-first workflow and is not current runtime behavior, setup
guidance, or an implementation contract. It is preserved because it captured
useful language for thinking about task, workspace, and evidence continuity.

## Historical Decision

SFE should not integrate TPCE directly. The useful lesson was narrower: SFE
needs its own compact vocabulary for live-workspace continuity without adopting
TPCE as a runtime dependency.

At the time, the TUI was accumulating concepts that overlapped with TPCE-style
continuity language: active workspace, active task, discovered files, selected
context, pending proposals, router review, safe apply boundaries, worktree
isolation, and continuity between discovery, patch, review, and apply.

## Useful Terms

`WorkspaceOrientation`

Records where SFE believes it is operating: launch directory, workspace root,
active checkout or worktree, workspace mode, optional worktree session identity,
and current Git identity where available. The useful lesson is that workspace
identity should be explicit enough to detect stale target or worktree reuse.

`TaskTrace`

Records the active user task and whether later actions still belong to that
task. The practical version is a task hash, task source, active/superseded
status, and enough metadata to prevent applying work from an old request to a
new one.

`EvidenceReference`

Records what SFE actually discovered, loaded, selected, proposed, reviewed, or
modified. The useful distinction is between a path mentioned by a provider and
a path SFE actually inspected. Evidence records should be path-based and
content-safe by default.

`ContinuityState`

An optional aggregate tying workspace orientation, task trace, evidence refs,
selected refs, pending proposal identity, and decision events into one
inspectable workflow state. The useful lesson is auditability, not a general
cognitive state engine.

## Historical Continuity Issues

The original note named practical discontinuities SFE could detect without
importing TPCE:

- a write-oriented command with no active task;
- workspace or worktree changed after discovery;
- pending work created from an older task, selected context, or workspace;
- provider output touching paths outside the discovered or selected trace;
- provider output proposing files SFE never inspected;
- router review with incomplete current file or discovery metadata;
- apply/promote requested against a different worktree session.

These remain useful design concerns, but this document does not define the
current runtime event schema or exact command behavior.

## Lessons

- Keep SFE continuity vocabulary engineering-specific and workspace-focused.
- Do not store raw file contents, `.env` values, provider payloads, API keys, or
  hidden prompt content in diagnostic traces by default.
- Treat trace/export ideas as optional observability, not as a dependency on a
  separate continuity engine.
- Preserve a clear boundary between current runtime contracts and speculative
  vocabulary.
