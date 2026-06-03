# Google Gemini Progressive Benchmark Note

This note records the first limited Google/Gemini benchmark attempt after adding
the Google provider path. It is not a reliability benchmark, not a statistical
provider comparison, and not production validation.

## Configuration

- Provider path: `google`
- API style: Gemini OpenAI-compatible Chat Completions
- Model: `gemini-2.5-flash-lite`
- Raw reports were written under `/tmp` and were not committed.
- No API keys or local credential values are included here.

## Smoke Test

Command:

```bash
python runtime/run_google_smoke.py --model gemini-2.5-flash-lite
```

Result: the live smoke test returned `GOOGLE_OK`.

## Large/Contextual Limit-1 Fixture Smoke

Command shape:

```bash
python runtime/run_large_contextual_benchmark.py \
  --executor google \
  --model gemini-2.5-flash-lite \
  --task-tier standard \
  --selection-mode fixture \
  --repeat 1 \
  --limit 1 \
  --max-tokens 240
```

Result summary:

- Task: `large_contextual_payments_failover`
- Baseline success: `100%`
- Spatial fixture success: `100%`
- Baseline total tokens: `2342`
- Spatial total tokens: `472`
- Input token reduction: `81.54%`
- Total token reduction: `79.85%`
- Router runs: `0`

Interpretation: the fixture-only smoke validated basic Google executor wiring on
one standard-tier large/contextual task.

## Large/Contextual Limit-1 Router-Inclusive Smoke

Command shape:

```bash
python runtime/run_large_contextual_benchmark.py \
  --executor google \
  --model gemini-2.5-flash-lite \
  --router-model gemini-2.5-flash-lite \
  --task-tier standard \
  --selection-mode both \
  --repeat 1 \
  --limit 1 \
  --max-tokens 240
```

Result summary:

- Task: `large_contextual_payments_failover`
- Baseline success: `100%`
- Fixture spatial success: `100%`
- Router spatial success: `100%`
- Router selected block: `pay-ops`
- Expected fixture block: `pay-ops`
- Router valid selection rate: `100%`
- Router selection match rate: `100%`
- Router executor input token reduction: `81.45%`
- Router-inclusive input token reduction: `12.44%`

Interpretation: this tiny router-inclusive smoke showed positive preliminary
behavior. The router selected the expected block and the executor completed the
task, but the sample is one task and one repeat only.

## Full Standard Repeat-1 Attempt

The next progressive step attempted the full standard tier with repeat 1 and
`selection-mode both`.

Expected scale:

- Standard-tier tasks: `7`
- Benchmark runs: `21`
- Live executor calls: `21`
- Live router calls: `7`
- Expected total live Google calls: `28`

The run was not clean. It hit Google/Gemini HTTP `429 RESOURCE_EXHAUSTED`
quota/rate-limit errors before completing clean provider coverage. The observed
free-tier limits were approximately:

- `10` requests per minute
- `250K` tokens per minute
- `20` requests per day

The failures were quota-related. The artifacts did not show malformed router
JSON, empty router output, or a clear model-quality failure as the primary stop
condition. Router fallbacks occurred after provider rate-limit errors.

## Stop Decision

Google/Gemini support was integrated successfully, and `gemini-2.5-flash-lite`
showed positive preliminary behavior on the smoke and limit-1 large/contextual
runs. The available data is too limited for strong claims.

The Google/Gemini benchmark campaign was stopped because the available free-tier
request quotas are too restrictive for provider comparison work. No repeat-3,
practical, high_context, structural, effectiveness, or output-variation Google
campaign was run in this phase.

Future Google/Gemini benchmark results should be treated as preliminary unless
they are rerun on a billing tier or another quota arrangement that can support
the full provider-comparison protocol without rate-limit interruption.
