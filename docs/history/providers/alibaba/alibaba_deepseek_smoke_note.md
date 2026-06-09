# Alibaba DeepSeek Benchmark Smoke Note

This note records a cautious Alibaba Model Studio DeepSeek smoke test for SFE
benchmark use. It is not a full campaign, not a structural 50k run, and not a
statistical reliability result.

Alibaba thinking was disabled through the
benchmark provider configuration.

## Configuration

- Provider: `alibaba-api`
- Router candidate: `deepseek-v4-flash`
- Executor candidate: `deepseek-v4-pro`
- API style: OpenAI-compatible Chat Completions
- Thinking disabled: `true`

## Connectivity Smokes

Both model IDs responded to tiny exact-output prompts.

| Model | Prompt Target | Response | Total Tokens | Latency |
| --- | --- | --- | ---: | ---: |
| `deepseek-v4-flash` | `DEEPSEEK_FLASH_OK` | `DEEPSEEK_FLASH_OK` | 22 | 1097 ms |
| `deepseek-v4-pro` | `DEEPSEEK_PRO_OK` | `DEEPSEEK_PRO_OK` | 20 | 1250 ms |

No reasoning-token field was returned in these tiny responses.

## High-Overlap Selector Repeat-3

Fixture: `high_overlap_cassini_policy_exception_gate`

- Router model: `deepseek-v4-flash`
- Expected authoritative ID: `cassini-v31`
- Selected ID: `cassini-v31` in all 3 runs
- Honest selector pass: `3/3`
- Exact authoritative selection rate: `100.00%`
- JSON parse failures: `0`
- Fallback count: `0`
- Provider error count: `0`
- Total prompt tokens: `2142`
- Total completion tokens: `211`
- Total tokens: `2353`
- Per-run total tokens: `790`, `783`, `780`
- Per-run latency: `1737 ms`, `1743 ms`, `1559 ms`

Raw report: `/tmp/sfe_alibaba_deepseek_high_overlap_selector_repeat3.json`

## Limited Router+Executor Smoke

The generic effectiveness benchmark was run once with:

- Router: `alibaba-api` / `deepseek-v4-flash`
- Executor: `alibaba-api` / `deepseek-v4-pro`
- Repeat: `1`
- Max output tokens: `96`

Summary:

- Paired runs: `10`
- Scoring paired runs: `9`
- Router success rate: `100.00%`
- JSON valid rate: `100.00%`
- Fallback rate: `0.00%`
- Real routing accuracy: `100.00%`
- Provider error count: `0`
- Effective by target metric: `false`
- Quality-preserving savings rate: `0.00%`
- Wins/losses/ties: `0/9/1`
- Baseline failure rate: `20.00%`
- Spatial failure rate: `10.00%`

Token summary:

- Baseline executor tokens: `2338`
- Spatial router tokens: `12723`
- Spatial executor tokens: `2649`
- Recorded spatial end-to-end tokens: `12313`

The spatial token fields need cautious interpretation in this generic
effectiveness report: the recorded spatial end-to-end total does not directly
equal router tokens plus executor tokens for this run. Use these values as
benchmark-report diagnostics, not as a clean cost accounting comparison.

The router diagnostics recorded thinking disabled as `true`. The benchmark
metadata still prints a legacy `router_disable_thinking: False` field for
non-`llm` router names; the Alibaba provider diagnostics are the relevant
source for this run.

Raw reports:

- `/tmp/sfe_alibaba_deepseek_effectiveness_repeat1.json`
- `/tmp/sfe_alibaba_deepseek_effectiveness_repeat1.md`

## Interpretation

The DeepSeek pair is usable at the connectivity and high-overlap selector smoke
level. The `deepseek-v4-flash` router produced valid JSON, selected the
authoritative high-overlap document in three consecutive runs, and did not use
fallback.

The limited router+executor effectiveness run is primarily wiring and routing
evidence. It was not an effectiveness win, and deterministic wording-guard
corrections appeared during routing. It should not be treated as a quality or
cost comparison against the completed Alibaba Qwen benchmark phase.

Structural 50k was intentionally not run for this DeepSeek smoke.
