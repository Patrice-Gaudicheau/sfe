# SFE Effectiveness Benchmark

This page preserves one strict Lemonade executor plus LLM router benchmark result.

## Reproduction Command

```bash
python runtime/run_effectiveness_benchmark.py \
  --executor lemonade \
  --router llm \
  --repeat 3 \
  --strict \
  --json logs/effectiveness_llm_lemonade_strict_successful_pairs.json \
  --md logs/effectiveness_llm_lemonade_strict_successful_pairs.md
```

## Setup

- Executor: `lemonade`
- Router: `llm`
- Router model: `Qwen3-0.6B-GGUF`
- Executor model: `Qwen3.5-35B-A3B-GGUF`
- Task set: `benchmarks/tasks.json`
- Task count: `10`
- Repeat count: `3`
- Paired runs: `30`
- Strict scoring: `true`

Preserved benchmark artifacts:

- `logs/effectiveness_llm_lemonade_strict_successful_pairs.json`
- `logs/effectiveness_llm_lemonade_strict_successful_pairs.md`

Artifact hashes:

```text
271c701a3bf5cc55c577486ee83a86892029e038557767ce1bc58089bc7bd267  logs/effectiveness_llm_lemonade_strict_successful_pairs.json
14e72f3b1ee111cd5e814c6de6a09a922b4404f1c15228cd06faa91ef5ab4d65  logs/effectiveness_llm_lemonade_strict_successful_pairs.md
```

## Aggregate Metrics

| Metric | Value |
| --- | ---: |
| Mean total token savings | 27.89% |
| Median total token savings | 22.54% |
| Mean quality delta | +0.183 |
| Wins / losses / ties | 30 / 0 / 0 |
| Router success rate | 100.00% |
| JSON valid rate | 100.00% |
| Fallback rate | 0.00% |
| Routing accuracy | 100.00% |
| Baseline failure rate | 30.00% |
| Spatial failure rate | 0.00% |

## Successful Pairs Only

This subset includes only pairs where both `baseline.success` and `spatial.success` are true.

| Metric | Value |
| --- | ---: |
| Paired count | 21 |
| Mean total token savings | 21.40% |
| Median total token savings | 20.00% |
| Wins / losses / ties | 21 / 0 / 0 |

Successful-pairs-only reporting matters because it avoids inflating the spatial result when the baseline times out or fails. The subset asks a narrower question: when both systems produce successful outputs under this benchmark's checks, does spatial execution still save tokens? In this run, it does.

## Task-Type Breakdown

| Task type | Runs | Mean token savings | Mean quality delta | W/L/T |
| --- | ---: | ---: | ---: | ---: |
| `analysis` | 6 | 36.08% | +0.345 | 6/0/0 |
| `coding` | 3 | 14.22% | 0.000 | 3/0/0 |
| `multi_context` | 6 | 26.05% | +0.318 | 6/0/0 |
| `planning` | 3 | 37.45% | 0.000 | 3/0/0 |
| `review` | 3 | 49.94% | +0.500 | 3/0/0 |
| `writing` | 9 | 17.69% | 0.000 | 9/0/0 |

## Interpretation

The result supports the narrower claim that SFE reduced token usage while preserving the benchmark's heuristic success checks on this mixed task set.

The result appears positive here because:

- Role separation keeps execution prompts aligned to the work type instead of using a single broad assistant frame.
- Reduced unnecessary context removes generic baseline instructions that are not needed for many tasks.
- Specialized prompts preserve task-relevant constraints while avoiding unrelated planning, analysis, or coding scaffolding.
- The hardened routing contract keeps router output valid JSON and prevents router collapse into a single task type.
- Strict benchmark scoring prevents invalid spatial runs from being counted as successful wins.
- Successful-pairs-only validation confirms savings remain when failed baseline runs are removed from the comparison.

## What This Shows in This Benchmark

This benchmark shows that, for the current 10-task mixed benchmark repeated 3 times on the configured Lemonade models, SFE spatial execution produced lower total token usage than baseline execution while preserving the benchmark's measured success checks. It also shows that the router contract remained stable in this run: all routing outputs were valid, no fallback was needed, and task-type routing accuracy was 100%.

## What It Does Not Prove Yet

This result does not prove that SFE will generalize across larger task sets, different model families, external tool use, longer multi-step work, or non-heuristic evaluation. It also does not isolate every causal factor; role separation, prompt specialization, and reduced context are tested together as the current SFE execution path.

## Limitations

- The benchmark set is small.
- Scoring is heuristic and should be supplemented with stronger evaluators.
- Results depend on the local Lemonade server and configured models.
- Baseline timeout effects can make aggregate SFE results look stronger than successful-pairs-only results.
- Larger task sets and repeated model comparisons are needed before making broad claims.

## Next Steps

- Expand the benchmark task count and include more task variants per type.
- Add stronger scoring, including exact-match cases and optional LLM-judge evaluation.
- Compare against larger baseline models.
- Test smaller spatial executors to measure whether routing enables cheaper execution without quality loss.
