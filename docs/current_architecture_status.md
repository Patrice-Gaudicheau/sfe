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
read-only executor boundary.

The currently validated TUI commands are:

- `/help`
- `/pwd`
- `/status`
- `/context`
- `/files`
- `/task`
- `/dry-run`
- `/ask`
- `/patch`
- `/reset`

`/dry-run` uses the local provider-free `local_lexical_preview` router. It is
deterministic and useful for previewing selected segment ids, token estimates,
score categories, and fallback reasons. It is not an LLM router result.

`/ask` uses `DirectBackend`, selected context, protected instructions, and the
protected task to produce a read-only answer. It does not use the proxy, switch
backends, write files, execute shell commands, or run an agent loop.

`/patch` is proposal-only. It may ask the read-only executor for a unified diff
or a brief explanation of why no safe diff can be proposed. It must not apply
file changes, modify the workspace, run shell commands, or imply that files were
changed. Any future write/apply workflow needs a separate design and explicit
confirmation boundary.

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
- a safe design for any future write/apply workflow after `/patch`;
- stronger evidence for real Responses streaming context replacement before it
  is treated as generally usable;
- clearer operational guidance for secrets, logs, provider limits, and local
  proxy exposure.

The current status is therefore: TUI plus `DirectBackend` is the primary
architecture direction; proxy work is standby experimental compatibility and
research infrastructure; practical value remains to be demonstrated with
controlled, repeatable workflows.
