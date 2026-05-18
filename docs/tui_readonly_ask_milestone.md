# TUI Read-Only Ask Milestone

This note records the first useful end-to-end first-party SFE TUI milestone.

The read-only `/ask` path is live through the DirectBackend. The flow is:

- choose a workspace,
- load explicit files into `context_segments`,
- route reducible segments with `local_lexical_preview`,
- send only selected context plus protected instructions and the protected task
  to the read-only executor,
- render the assistant answer with sanitized routing diagnostics.

A manual smoke test loaded 7 files, selected 3 of 7 context segments, and
reported an estimated 38.92% selected-context token reduction. The selected
context was then sent to the read-only executor and produced a grounded answer.
Writes and shell execution remained disabled, and the provider was called once.

This is an anecdotal smoke result, not a benchmark. It validates the first
SFE-aware TUI path from explicit file context to local routing to read-only
answering, but it does not establish reliability or general reduction quality.

A follow-up 7-file smoke loaded the TUI router, backend, contract, app,
renderer, tests, and DirectBackend strategy note. It selected 3 of 7 files with
an estimated 36.58% reduction and `/ask` completed successfully. `/context`
showed selected and unselected files safely with opaque ids, workspace-relative
refs, score categories, and no file contents. The smoke also exposed a ranking
limitation: for a router-specific task, docs/tests/renderer content could outrank
the router implementation file. The next local-router improvement is
source/path-aware lexical ranking.

No write tools, shell execution, proxy calls, backend switching, or agent loop
are part of this milestone. The next phases remain context inspection, patch
generation, and only later carefully scoped write tools.
