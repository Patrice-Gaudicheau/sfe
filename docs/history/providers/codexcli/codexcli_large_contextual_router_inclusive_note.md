# CodexCLI Large Contextual Router-Inclusive Note

This note records the first benchmark-local CodexCLI router-inclusive
validation on the large/contextual practical tier. It is not full SFE runtime
support and should not be read as `/run`, TUI, discovery, DEV patch, resume,
output repair, or shared `SFE_PROVIDER` validation.

## Scope

- Provider path: `openai-codexcli`
- Transport: `codex exec --json` through `providers/codexcli.py`
- Benchmark path: `runtime/run_large_contextual_benchmark.py`
- Selection mode: `both`
- Executor model: `gpt-5.4-mini`
- Router model: `gpt-5.5`
- Raw reports were written under `/tmp` and were not committed.
- No credentials, account details, or local secrets are included here.

## Prior Fixture Baseline

Before router-inclusive validation, the practical fixture repeat-3 run completed
successfully:

- `3` practical tasks
- `3` repeats
- `18` live CodexCLI executor calls
- Baseline success: `9/9`
- Spatial fixture success: `9/9`
- Average input token reduction: `41.27%`
- Average total token reduction: `40.64%`
- No visible stderr, idle supervision failure, JSONL parsing issue, empty
  output, missing usage, or validation failure.

## Router-Inclusive Practical Results

Each router-inclusive run used one task, repeat `1`, selection mode `both`, and
four live CodexCLI calls: baseline executor, spatial fixture executor, router
selector, and spatial router executor.

| Task | Baseline | Fixture | Router | Router block | Confidence | Fallback | Fixture input reduction | Router executor input reduction |
| --- | --- | --- | --- | --- | ---: | --- | ---: | ---: |
| `large_contextual_long_aquila_entitlements_replay` | pass | pass | pass | `aquila-r3-final` | 1.00 | false | 41.42% | 41.42% |
| `large_contextual_long_meridian_gateway_budget` | pass | pass | pass | `mgb19-final` | 0.99 | false | 41.23% | 41.23% |
| `large_contextual_long_cobalt_dispatch_reconciliation` | pass | pass | pass | `cr88-final` | 0.99 | false | 41.16% | 41.16% |

For all three tasks, the router-selected block matched the expected fixture
block and the valid selection rate was `100%`. The Cobalt fixture and router
answers both preserved the exact marker `oxygen-critical`.

Infrastructure observations across the router-inclusive campaign:

- `12` live CodexCLI calls completed.
- `9` calls were executor calls.
- `3` calls were router calls.
- No visible stderr was observed.
- No non-zero return code was observed.
- No idle supervision failure was observed.
- No JSONL parsing issue was observed.
- No malformed router output was observed.
- No empty selection was observed.
- No empty output was observed.
- No missing usage was observed.
- No validation failure was observed.
- No fallback was used.

## Interpretation

CodexCLI works as a benchmark-local router and executor for the tested
large/contextual practical `both` mode. The router selected the exact expected
block in all three practical tasks, and executor-context reduction remained
stable at approximately `41%`.

The one-shot router-inclusive total token cost was higher than baseline in all
three runs because the router call cost outweighed the saved executor context.
The current demonstrated value is cognitive separation and executor-context
reduction, not one-shot total-token savings for practical-tier tasks.

Future work could test cheaper router models, router reuse, larger contexts,
multi-executor amortization, selective router activation, and eventually DEV
patch workloads. CodexCLI remains intentionally unwired from `/run`, discovery
routing, TUI, and shared `SFE_PROVIDER`.
