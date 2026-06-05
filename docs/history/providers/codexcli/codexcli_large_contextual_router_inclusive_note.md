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
- Initial single-task model pairing: executor `gpt-5.4-mini`, router `gpt-5.5`
- Aligned repeat-3 model pairing: executor `gpt-5.4`, router `gpt-5.4`
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

## Aligned GPT-5.4 Repeat-3 Results

CodexCLI defaults were later aligned with the OpenAI API `.env` model pairing:

- `DEFAULT_ROUTER_MODEL = "gpt-5.4"`
- `DEFAULT_EXECUTOR_MODEL = "gpt-5.4"`
- Commit: `c49cde9` Align CodexCLI default models with OpenAI API

Phase 5.5 later kept these provider defaults but decoupled CodexCLI model
environment variables from OpenAI API model variables. Current CodexCLI paths
use `SFE_CODEXCLI_ROUTER_MODEL` and `SFE_CODEXCLI_EXECUTOR_MODEL`.

The aligned repeat-3 run used:

```bash
python runtime/run_large_contextual_benchmark.py \
  --executor openai-codexcli \
  --selection-mode both \
  --task-tier practical \
  --repeat 3 \
  --model gpt-5.4 \
  --router-model gpt-5.4 \
  --max-tokens 300
```

The run passed:

- `3` practical tasks
- `3` repeats
- `36` live CodexCLI calls
- `27` executor result rows
- `9` router selector calls
- Baseline success: `9/9`
- Spatial fixture success: `9/9`
- Spatial router success: `9/9`
- Router valid selection rate: `100%`
- Router match rate: `100%`
- Fallback count: `0`
- Context reduction verified: `true`

Per-task routing remained stable:

| Task | Expected block | Router block | Success |
| --- | --- | --- | --- |
| `large_contextual_long_aquila_entitlements_replay` | `aquila-r3-final` | `aquila-r3-final` | `3/3` |
| `large_contextual_long_meridian_gateway_budget` | `mgb19-final` | `mgb19-final` | `3/3` |
| `large_contextual_long_cobalt_dispatch_reconciliation` | `cr88-final` | `cr88-final` | `3/3` |

Overall token results distinguished executor-context reduction from
router-inclusive total-token cost:

| Scope | Input reduction | Total reduction |
| --- | ---: | ---: |
| Fixture executor only | 40.60% | 40.06% |
| Router-selected executor only | 40.60% | 40.20% |
| Router-inclusive | -24.06% | -24.58% |

The aligned repeat-3 run therefore validated cognitive separation and
executor-context reduction, not one-shot total-token savings. Router-inclusive
totals remained higher than baseline because the router call cost outweighed
the saved executor context in these practical-tier one-shot runs.

Additional observations:

- Cobalt preserved the exact marker `oxygen-critical` in all baseline,
  fixture, and router outputs.
- No visible stderr, non-zero return code, idle supervision failure, JSONL
  parsing issue, malformed router output, empty selection, empty output,
  missing usage, validation failure, or fallback was observed.
- One confidence-field caveat was recorded: Aquila repeat `2` reported router
  confidence `0.0` despite selecting `aquila-r3-final`, matching the fixture,
  producing no router error, using no fallback, and passing executor
  validation. Treat confidence as a field to monitor in cross-provider
  comparisons.

## Interpretation

CodexCLI works as a benchmark-local router and executor for the tested
large/contextual practical `both` mode. The router selected the exact expected
block in all practical tasks, and executor-context reduction remained stable at
approximately `40-41%`.

The one-shot router-inclusive total token cost was higher than baseline because
the router call cost outweighed the saved executor context. The current
demonstrated value is cognitive separation and executor-context reduction, not
one-shot total-token savings for practical-tier tasks.

Future work could test cheaper router models, router reuse, larger contexts,
multi-executor amortization, selective router activation, and eventually DEV
patch workloads. CodexCLI remains intentionally unwired from `/run`, discovery
routing, TUI, and shared `SFE_PROVIDER`.
