# TUI V0.1 User Guide

This guide documents the current canonical first-party SFE-aware TUI behavior.
It is a prototype workflow guide, not a production-readiness claim.

The canonical user-facing path is the TUI with `DirectBackend`. The proxy and
proxy-backed experiments are not the primary user path and are not required for
this guide.

## What The TUI Is

The SFE-aware TUI is a command-line interactive workflow for loading explicit
local text files as context, setting a task, previewing local context routing,
and optionally asking a configured read-only executor/provider for an answer or
patch proposal.

The TUI keeps the current task, selected workspace, loaded context metadata,
local routing diagnostics, and latest ask/patch result in the session. It does
not run shell commands, execute tools, switch backends, or apply patches.

## Launch

From the repository root:

```bash
python -m sfe_tui
```

At startup, select a workspace or accept the current directory. The TUI displays
workspace paths using safe relative labels where possible.

## Canonical Workflow

1. Check the selected workspace:

   ```text
   /pwd
   ```

2. Load one or more local text files as context. This replaces the currently
   loaded context:

   ```text
   /files <path>
   ```

3. Set the task:

   ```text
   /task <text>
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

7. Request a patch proposal without applying it:

   ```text
   /patch
   ```

8. Clear the session state while preserving the workspace:

   ```text
   /reset
   ```

## Command Reference

- `/help`: show concise command help.
- `/pwd`: show the selected workspace using safe display conventions.
- `/status`: show safe TUI state, latest result metadata, and disabled
  capabilities.
- `/context`: show loaded context segment count, opaque ids, safe source refs,
  approximate sizes/tokens, latest selected ids, and skipped/rejected metadata.
- `/files <paths...>`: replace the loaded context with the provided text files.
  Directory inputs and unsupported files are rejected or skipped with a reason.
- `/task <text>`: store the current task. Empty tasks are rejected.
- `/dry-run`: build the SFE contract and run a local routing preview.
- `/ask`: send selected context plus protected task/instructions to the
  configured read-only executor/provider.
- `/patch`: ask for a patch proposal only. The proposal is not applied.
- `/reset`: clear task, context, latest routing/result, and skipped/rejected
  context state; preserve the selected workspace.
- `/quit` and `/exit`: exit the TUI.

## Dry Run

`/dry-run` is a local preview. It uses the provider-free
`local_lexical_preview` router to estimate which loaded context segments would
be selected for the current task.

It reports preflight state, selected opaque segment ids, safe source refs,
approximate token counts, fallback reasons where available, and safety flags.
It does not call the executor/provider, write files, execute shell commands, or
apply patches.

## Ask

`/ask` routes the loaded context locally, then sends only the selected context
segments, protected instructions, and protected task to the configured
read-only executor/provider.

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
- patch application is disabled.

The TUI may display the provider's proposed diff or explanation. It does not
apply that diff, run shell commands, execute tools, or modify the workspace.

## Safety Guarantees

The current TUI behavior intentionally keeps these boundaries:

- no shell execution;
- no tool execution;
- no backend switching;
- patch application disabled;
- `/dry-run` makes no executor/provider call;
- `/patch` is proposal-only and does not write files;
- workspace and source paths are displayed using safe relative labels where
  possible;
- diagnostics do not display raw file contents, request bodies, provider
  payloads, API keys, or authorization headers.

## Current Limitations

- The router is a local lexical preview, not an LLM router result.
- Routing quality is not yet proven across repeated realistic workflows.
- `/patch` does not apply patches.
- There is no CLI/API pipeline integration for the canonical TUI workflow yet.
- There is no provider-backed TUI router yet.
- The proxy remains experimental compatibility and observability
  infrastructure; it is not the canonical user path.
- The current test suite validates expected behavior and safety boundaries, but
  it does not establish production reliability or general practical value.

## First Smoke Test

Use a small local text file inside the selected workspace:

```bash
cd /tmp
printf "SFE routing note: alpha context is relevant for the smoke test.\n" \
  > sfe-smoke-note.txt
python -m sfe_tui
```

In the TUI, accept `/tmp` as the current workspace, then run:

```text
/pwd
/files sfe-smoke-note.txt
/task Explain the alpha context in one sentence.
/dry-run
/context
/ask
/patch
/reset
/quit
```

Expected observations:

- `/dry-run` reports local preview diagnostics and `provider calls made: 0`;
- `/context` shows opaque segment ids and safe source refs, not file contents;
- `/ask` requires a configured executor/provider before it can return an
  answer;
- `/patch` is clearly labeled as proposal-only and does not modify the file.
