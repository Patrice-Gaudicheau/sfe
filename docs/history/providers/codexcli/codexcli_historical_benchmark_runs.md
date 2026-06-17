# CodexCLI Historical Benchmark Runs

Status note: this is a historical rollup for granular CodexCLI run notes. It
preserves benchmark and diagnostic observations for audit continuity. CodexCLI
is an agentic CLI provider path, not a thin OpenAI API transport, and these
observations should not be read as current setup guidance or provider rankings.

## Mixed TUI `/run` Observation With OpenAI Discovery

One manual `sfe-tui` `/run` test used CodexCLI for execution-mode routing and
write execution, with OpenAI used for workspace discovery because CodexCLI
discovery routing was not implemented at the time.

Effective role split:

```env
SFE_PROVIDER_ROUTER=codexcli
SFE_PROVIDER_DISCOVERY=openai
SFE_PROVIDER_EXECUTOR=codexcli
SFE_CODEXCLI_ROUTER_MODEL="gpt-5.5"
SFE_CODEXCLI_EXECUTOR_MODEL="gpt-5.5"
SFE_CODEXCLI_SANDBOX=read-only
SFE_CODEXCLI_ROUTER_EFFORT="high"
SFE_CODEXCLI_EXECUTOR_EFFORT="high"
```

The run selected `workspace_write`, inspected 3 context candidates, selected 3
files, completed patch validation and promotion, and modified `public/index.php`
in a small PHP mini-blog fixture. Manual validation with `php -l` and a render
smoke test passed. This was one successful small-fixture observation, not a
broad reliability guarantee.

## Large/Contextual Practical Fixture Executor Runs

The first benchmark-local CodexCLI executor validation used:

- Provider path: `openai-codexcli`.
- Transport: `codex exec --json` through `providers/codexcli.py`.
- Selection mode: fixture only.
- Router calls: none.
- Executor model: `gpt-5.4-mini`.

The output-variation repeat-1 run completed 10 live executor calls without
JSONL parsing failures, idle-supervision failures, empty outputs, or missing
usage. Practical-tier large/contextual fixture runs passed for:

| Task | Baseline | Spatial fixture | Total reduction | Note |
| --- | --- | --- | ---: | --- |
| `large_contextual_long_aquila_entitlements_replay` | pass | pass | 41.28% | Required facts matched. |
| `large_contextual_long_meridian_gateway_budget` | pass | pass | 41.05% | Required facts matched. |
| `large_contextual_long_cobalt_dispatch_reconciliation` | pass | pass after retry | 41.04% | Prompt was tightened to preserve `oxygen-critical`. |

This validated CodexCLI as a benchmark-local executor for the tested paths. It
did not validate CodexCLI discovery, `/run`, router-inclusive mode, or shared
provider wiring by itself.

## Large/Contextual Router-Inclusive Runs

Router-inclusive practical validation used `runtime/run_large_contextual_benchmark.py`
with selection mode `both` and `codex exec --json`.

Initial single-task observations used executor `gpt-5.4-mini` and router
`gpt-5.5`. The router selected the expected blocks for Aquila, Meridian, and
Cobalt with no fallback, no malformed router output, no validation failure, and
stable executor-context reductions around 41%.

An aligned repeat-3 later used executor `gpt-5.4` and router `gpt-5.4`:

- 3 practical tasks.
- 3 repeats.
- 36 live CodexCLI calls.
- Baseline success: 9/9.
- Spatial fixture success: 9/9.
- Spatial router success: 9/9.
- Router valid selection rate: 100%.
- Router match rate: 100%.
- Fallback count: 0.

Per-task routing selected `aquila-r3-final`, `mgb19-final`, and `cr88-final` in
3/3 runs each. Executor-context reduction stayed around 40.60%, while
router-inclusive total-token reduction was -24.58% because the router call cost
outweighed saved executor context in these one-shot practical-tier runs.

## CodexCLI vs Direct OpenAI API Directional Comparison

A documentation-only comparison contrasted the CodexCLI practical repeat-3 run
with the closest existing direct OpenAI API evidence. It was not a strict parity
run because model versions, router model, max-output budget, and executor
success rates differed.

The key diagnosis was directional:

- CodexCLI router validity and match rate were 100%, so SFE routing quality was
  not the likely cause of the lower apparent token reduction.
- CodexCLI executor input reduction was about 40.60%, while the closest OpenAI
  API evidence reported about 88% selected reduction and about 63.40%
  router-inclusive reduction.
- The difference was more consistent with CodexCLI wrapping, orchestration,
  token-accounting differences, or a fixed agentic context envelope than with a
  selector failure.

The recommendation was to keep CodexCLI results provider-specific and avoid an
expensive mirror run unless explicitly needed.

## Raw CodexCLI Envelope Smoke

Tiny `codex exec --json` smoke tests used the trivial prompt `Return exactly:
ok` to isolate CodexCLI's fixed envelope.

| Command shape | Returned text | Input tokens | Output tokens | Interpretation |
| --- | --- | ---: | ---: | --- |
| Default plus `--ephemeral` | `ok` | 11,189 | 22 | Full CodexCLI exec-agent envelope. |
| Add `--ignore-user-config --ignore-rules` | `ok` | 9,256 | 5 | User config/rules removed about 1,933 input tokens. |
| Add plugin/app/tool/hook feature disables | `ok` | 8,045 | 16 | Feature disables removed another 1,211 input tokens. |

The constrained command still reported about 8k input tokens for a trivial
prompt. This supports treating CodexCLI as an agentic provider with a large
fixed envelope, not as a direct apples-to-apples token-efficiency baseline
against direct OpenAI API calls.

## Lessons

- CodexCLI can be useful for functional benchmark-local validation.
- CodexCLI token metrics should remain provider-specific because the CLI
  transport includes a large fixed agentic envelope.
- Executor-only and router-inclusive token metrics must be reported separately.
- Historical CodexCLI patch-era wording reflects the implementation state of
  those observations and should not be projected onto the current
  Aider-backed workspace-writer default.
