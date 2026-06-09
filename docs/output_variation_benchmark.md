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
reduction, and output expansion that offsets input reduction. The legacy
`output_expansion_offsets_input_reduction` field means output increased while
input decreased. Newer fields distinguish whether that expansion partially
offset input savings while total tokens still decreased, or fully offset input
savings so selected total tokens were flat or higher.

The benchmark also includes lightweight quality checks. Shorter output is not
automatically treated as better: required facts must be present, forbidden
distractor mentions must be absent, and the requested answer format must be
respected.

## Selection Sources

The default selection source is `fixture`. Fixture selection uses the
task's deterministic `selected_block_ids` and keeps the dry-run tests stable.

The optional `router` selection source uses the neutral SFE segment selector in
`sfe.segment_selector`. It does not use the SFE run pipeline or workspace
discovery. The benchmark still compares two executor modes only: full-context
`baseline` and `selected` context from the chosen selection source.

In router mode, there is no fallback to fixture selection. If the router fails
or returns no usable block IDs, the selected executor call is skipped and the
comparison is marked invalid. Router status, reason, confidence, error type,
selected IDs, latency, and estimated selected-input metadata are reported
alongside the run.

CLI router mode supports OpenAI, Anthropic, and Alibaba/Qwen providers. Fixture
mode remains deterministic and is still the default.

Executor token totals remain baseline-vs-selected executor costs. Router
selection overhead is reported separately when available and is not mixed into
executor input, output, or total token comparisons.

Router provider token usage, when captured by the neutral selector, is selection
metadata only. It is not included in baseline or selected executor totals unless
the benchmark explicitly adds router-inclusive accounting in a future revision.

Using a stronger or more expensive model for segment selection and a cheaper or
faster model for execution is a deliberate supported strategy. Configure that
with provider-specific router and executor model environment variables, or
override with `--router-model` and `--model`.

Example live OpenAI router/executor run:

```bash
OPENAI_API_KEY=... \
SFE_OPENAI_ROUTER_MODEL=... \
SFE_OPENAI_EXECUTOR_MODEL=... \
python runtime/run_output_variation_benchmark.py \
  --executor openai-api \
  --router-provider openai \
  --selection-source router
```

Example live Anthropic router/executor run:

```bash
ANTHROPIC_API_KEY=... \
SFE_ANTHROPIC_ROUTER_MODEL=... \
SFE_ANTHROPIC_EXECUTOR_MODEL=... \
python runtime/run_output_variation_benchmark.py \
  --executor anthropic \
  --router-provider anthropic \
  --selection-source router
```

Example live Alibaba/Qwen router/executor run:

```bash
ALIBABA_API_KEY=... \
SFE_ALIBABA_ROUTER_MODEL=... \
SFE_ALIBABA_EXECUTOR_MODEL=... \
python runtime/run_output_variation_benchmark.py \
  --executor alibaba-api \
  --router-provider alibaba \
  --selection-source router
```

Example live Google/Gemini router/executor run after setting `GOOGLE_API_KEY`,
`SFE_GOOGLE_MODEL`, and `SFE_GOOGLE_BASE_URL` in local `.env`:

```bash
python runtime/run_output_variation_benchmark.py \
  --executor google \
  --router-provider google \
  --selection-source router
```

## Exploratory Live Results

The following observations come from exploratory live runs after the benchmark
migrated to the neutral `sfe.segment_selector` path. They are not definitive
benchmark conclusions. Run sizes differ across providers, so the results are
indicative rather than statistically balanced. The intended strategy in these
runs was to use a stronger or more expensive model for segment selection and a
cheaper or faster model for execution.

OpenAI was tested through the neutral selector path with a minimal smoke run.
The selector chose `payments-cache`, quality was `true/true`, and total tokens
decreased. Output increased slightly in the smoke, but input savings dominated.

Anthropic was tested through the neutral selector path with a minimal smoke and
a `limit 5`, `repeat 1` run. The `limit 5` run produced five valid
comparisons. Average total tokens decreased from `303.6` to `238.4`, a delta of
`-65.2`. Output was nearly stable, with average output delta `-1.8`. One
selected quality failure occurred on `broad_synthesis`, where the selected
output missed the required fact `limited launch`. The current signal is stable
token reduction, but quality must be checked per task.

Alibaba/Qwen was tested through the neutral selector path with a minimal smoke
and a `limit 5`, `repeat 1` run after prompt/format alignment. The `limit 5`
run produced five valid comparisons and quality was `true/true` across the run.
Average total tokens decreased from `1016.2` to `945.2`, a delta of `-71.0`.
One full-offset case occurred on `ambiguous_diagnostic`: input decreased,
output increased heavily, and selected total tokens became higher. The
`broad_synthesis` task showed partial offset: output increased but total still
decreased. The current signal is aggregate total reduction, but output
expansion can erase savings on individual tasks.

SFE's direct effect remains input reduction. Output reduction is conditional
and depends on provider, task, prompt, and output contract. Total token
reduction can still happen when output increases, and output expansion can
partially or fully offset input savings. Quality metrics are necessary:
cheaper or shorter output is not automatically better.

Keep output variation as a dedicated benchmark for now. Do not merge these
results into the original benchmarks yet. For stronger provider comparison, run
balanced `limit 5`, `repeat 3` campaigns for Anthropic and Alibaba, or rerun all
providers with the same repeat count. Investigate task families with quality
failures or full-offset behavior before drawing product claims.
