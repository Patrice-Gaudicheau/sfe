# CodexCLI DEV/Patch Output-Token Benchmark Protocol

This note records the controlled benchmark protocol for evaluating whether SFE
can reduce output tokens in DEV/Patch mode when CodexCLI is the only live
provider.

## Scope

- Live calls are CodexCLI-only for financial reasons.
- Live OpenAI API, Anthropic, Google, Alibaba, Qwen API, DeepSeek API, and other
  paid API provider paths are out of scope for this campaign.
- The first goal is output-token behavior in DEV/Patch mode at comparable patch
  quality, not broad SaaS construction or provider comparison.
- Patch safety remains SFE-mediated: CodexCLI proposes text/diff only, and this
  benchmark parses, validates, isolates in a copied run workspace, applies, or
  records rejection through SFE patch utilities.

## Fixture Location

Default playground:

```bash
~/Projets/00_Tests/SFE-playground/codexcli-output-token-campaign
```

The fixture set contains small bounded projects:

- tiny static PHP blog without a database
- PHP form validation and filters, no database
- local JavaScript search/filtering
- CSS responsive layout fix
- PHP CSV export

Create or reset fixtures:

```bash
python runtime/run_codexcli_output_token_benchmark.py --reset-fixtures
```

## Comparison Conditions

The protocol compares SFE-mediated DEV/Patch prompt conditions:

- `selected_context_dev_patch`
- `full_context_dev_patch`

The full-context condition is a controlled prompt baseline using all fixture
context files. It is not a separate non-SFE provider pipeline and should be
reported with that limitation.

## Campaign Models

Campaign A:

```bash
SFE_PROVIDER=codexcli \
SFE_CODEXCLI_ROUTER_MODEL="gpt-5.4" \
SFE_CODEXCLI_EXECUTOR_MODEL="gpt-5.4" \
python runtime/run_codexcli_output_token_benchmark.py --live --max-tasks 1
```

Campaign B:

```bash
SFE_PROVIDER=codexcli \
SFE_CODEXCLI_ROUTER_MODEL="gpt-5.4" \
SFE_CODEXCLI_EXECUTOR_MODEL="gpt-5.4-mini" \
python runtime/run_codexcli_output_token_benchmark.py --live --max-tasks 1
```

The runner also accepts explicit `--router-model` and `--executor-model`
overrides. Model names are not hard-coded in the protocol logic.

## Safe Dry Run

Dry-run is the default when neither `--live` nor `--fake-provider` is passed. It
plans tasks and writes machine-readable artifacts without calling CodexCLI:

```bash
python runtime/run_codexcli_output_token_benchmark.py --dry-run --max-tasks 1
```

Local validation without live CodexCLI can use deterministic fake patch
responses:

```bash
python runtime/run_codexcli_output_token_benchmark.py \
  --fake-provider \
  --max-tasks 1 \
  --condition selected_context_dev_patch
```

## Output Artifacts

Each run writes a timestamped report directory under:

```bash
~/Projets/00_Tests/SFE-playground/codexcli-output-token-campaign/reports/
```

Artifacts:

- `runs.jsonl`: raw per-run records
- `runs.csv`: spreadsheet-friendly per-run metrics
- `summary.md`: human-readable campaign summary

Records distinguish measured provider usage from estimated fallback and missing
token data. CodexCLI JSONL usage metadata is preferred when available; otherwise
the benchmark marks fallback estimates explicitly.

## Future Reuse

Future API-provider campaigns may reuse the protocol if funding exists, but this
implementation deliberately does not add Qwen or DeepSeek executor support and
does not alter OpenAI, Anthropic, Google, Alibaba, or provider runtime behavior.
Live runs should remain limited and deliberate.
