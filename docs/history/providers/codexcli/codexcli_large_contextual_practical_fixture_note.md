# CodexCLI Large Contextual Practical Fixture Note

This note records the first successful benchmark-local CodexCLI executor
validation on the large/contextual practical fixture tier. It is not full SFE
runtime support and should not be read as `/run`, TUI, discovery, router, or
shared `SFE_PROVIDER` validation.

## Scope

- Provider path: `openai-codexcli`
- Transport: `codex exec --json` through `providers/codexcli.py`
- Benchmark paths validated:
  - controlled output-variation executor dispatch
  - large/contextual fixture executor mode
- Router calls: none
- Selection mode: fixture only
- Raw reports were written under `/tmp` and were not committed.
- No credentials, account details, or local secrets are included here.

## Relevant Commits

- `ccf193d` Strengthen CodexCLI provider adapter tests
- `d5da4bd` Add CodexCLI output variation benchmark dispatch
- `e8396ca` Clarify CodexCLI idle supervision semantics
- `37a3a7a` Set CodexCLI default router and executor models
- `2ce3fca` Add CodexCLI large contextual fixture executor
- `acb15e7` Fix CodexCLI large contextual idle supervision
- `f65e4b2` Preserve exact markers in large contextual prompts

## Output-Variation Smoke

A controlled output-variation repeat-1 run completed with `10` live CodexCLI
executor calls: baseline and selected execution for all five task families.
There were no router calls, JSONL parsing failures, idle supervision failures,
empty outputs, or missing usage.

## Large/Contextual Practical Fixture Results

All practical-tier runs used fixture selection and `gpt-5.4-mini` as the
CodexCLI executor model. Each task made two live CodexCLI executor calls:
baseline plus spatial fixture.

| Task | Baseline | Spatial fixture | Total reduction | Notes |
| --- | --- | --- | ---: | --- |
| `large_contextual_long_aquila_entitlements_replay` | pass | pass | 41.28% | Required facts matched. |
| `large_contextual_long_meridian_gateway_budget` | pass | pass | 41.05% | Required facts matched. |
| `large_contextual_long_cobalt_dispatch_reconciliation` | pass | pass after retry | 41.04% | First spatial answer paraphrased away `oxygen-critical`; prompt was tightened to preserve exact markers. |

Infrastructure observations across the successful practical fixture campaign:

- `6` live CodexCLI large/contextual executor calls completed.
- No router calls were made.
- No visible stderr was observed.
- No non-zero return code was observed.
- No idle supervision failure occurred after the CodexCLI idle-timeout fix.
- No JSONL parsing issue was observed.
- No empty output was observed.
- No missing usage was observed.
- `codexcli_idle_timeout_seconds` was left unset, so shared provider idle
  supervision policy applied.

## Interpretation

This validates `openai-codexcli` as a benchmark-local executor for the tested
output-variation and large/contextual fixture paths. It does not validate
CodexCLI as an SFE router, does not validate router-inclusive large/contextual
mode, and does not make CodexCLI a first-class runtime provider.

CodexCLI remains intentionally unwired from:

- `/run`
- discovery routing
- TUI executor factory
- shared `SFE_PROVIDER`

Future work remains:

- CodexCLI router-provider phase
- CodexCLI executor-provider phase for `/run` if explicitly accepted
- DEV patch executor support
- DEV patch micro-benchmark
