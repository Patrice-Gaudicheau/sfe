# Output Variation Benchmark

The output variation benchmark is a controlled benchmark family for observing
whether fixture-selected SFE-style context changes output token counts compared
with full-context baseline execution.

This benchmark is intentionally separate from the large/contextual benchmark.
The large/contextual benchmark primarily measures input-context reduction. The
output variation benchmark uses task families where output length can vary
because of ambiguity, broad synthesis pressure, patch-planning false leads,
strict output contracts, or distractor inflation.

## Dry-Run Interpretation

Dry-run fixture outputs are deterministic synthetic outputs used to validate the
benchmark pipeline, quality checks, and token-accounting logic. They are not
evidence that SFE reduces or increases output tokens in real LLM behavior.

Real output-token behavior requires live model execution. Even then, output
reduction is conditional: selected context can reduce, increase, or leave output
length stable depending on the task, prompt, model behavior, and output
contract.

## Metrics

The benchmark reports baseline and selected input, output, and total tokens,
plus output delta, output ratio, input and total reduction percentages, and
flags for output reduction, output increase, near-equal output, total-token
reduction, and output expansion that offsets input reduction.

The benchmark also includes lightweight quality checks. Shorter output is not
automatically treated as better: required facts must be present, forbidden
distractor mentions must be absent, and the requested answer format must be
respected.

## Selection Sources

The default selection source is `fixture`. Fixture selection uses the
task's deterministic `selected_block_ids` and keeps the dry-run tests stable.

The optional `router` selection source uses the proxy shadow-router path:
`ShadowRouterInput`, `create_shadow_router`, and
`ShadowRouterResult.candidate_selected_segment_ids`. It does not use the SFE
run pipeline and does not use workspace discovery. The benchmark still compares
two executor modes only: full-context `baseline` and `selected` context from the
chosen selection source.

In router mode, there is no fallback to fixture selection. If the router fails
or returns no usable block IDs, the selected executor call is skipped and the
comparison is marked invalid. Router status, reason, confidence, error type,
selected IDs, latency, and estimated selected-input metadata are reported
alongside the run.

CLI router mode requires `--executor openai-api`. This avoids mixing live router
selection with deterministic synthetic fixture outputs.

Executor token totals remain baseline-vs-selected executor costs. Router
selection overhead is reported separately when available and is not mixed into
executor input, output, or total token comparisons.

Actual router provider token usage is not currently included because the current
shadow-router result does not expose provider-reported router token usage. The
available router fields are selection metadata and router-estimated selected
input values, not billable router input/output token accounting.

Example live OpenAI router/executor run:

```bash
SFE_PROXY_SHADOW_ROUTER_PROVIDER=openai \
OPENAI_API_KEY=... \
SFE_OPENAI_ROUTER_MODEL=... \
SFE_OPENAI_EXECUTOR_MODEL=... \
python runtime/run_output_variation_benchmark.py \
  --executor openai-api \
  --selection-source router
```
