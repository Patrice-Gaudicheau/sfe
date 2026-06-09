# Alibaba Comparable Benchmark Runs

This note summarizes a limited Alibaba Model Studio replay of benchmark families that already have OpenAI or Anthropic coverage in the repository. It is a small comparability pass, not a statistical reliability benchmark and not a provider ranking.

Alibaba calls used the benchmark-only provider path with Qwen thinking disabled.

## Configuration

- Router provider/model: `alibaba-api` / `qwen3.6-flash`
- Executor provider/model: `alibaba-api` / `qwen3.6-plus`
- Thinking disabled: true
- API style: OpenAI-compatible Chat Completions
- Raw generated reports: `/tmp/sfe_alibaba_comparable_*.json`

## Reference Families

The replay was based on benchmark families documented for OpenAI and Anthropic, including:

- effectiveness benchmark notes
- high-overlap selector notes
- multi-zone synthetic notes
- large/contextual benchmark notes
- structural 50k notes

Some runner paths are provider-specific. Where Alibaba used an existing provider protocol or a small inline adapter instead of a first-class CLI option, the result is treated as comparable smoke evidence rather than an exact apples-to-apples campaign.

## Runs Completed

| Family | Scope | Result | Tokens | Latency |
| --- | --- | --- | --- | --- |
| Effectiveness | repeat-1 mixed task set | Router success 100.00%, JSON valid 100.00%, fallback 0.00%, real routing accuracy 100.00%. Effective by target metric: false. | Reported paired total: 16,856. Router total: 13,421. Executor total: 5,054. | Mean end-to-end spatial delta: +2166 ms. |
| High-overlap selector | repeat-3 selector-only, `high_overlap_cassini_policy_exception_gate` | 3/3 honest selector pass, selected `cassini-v31` each run, no fallback, no parse failure, no provider error. | Total: 2,511. Per-run total: 825, 859, 827. | Per-run latency: 1615 ms, 2081 ms, 1733 ms. |
| Multi-zone synthetic | one fixture, `multi_zone_synthetic_aurora_release_gate` | Honest multi-zone pass true, selected all required zones, omitted distractors, executor output parsed successfully, no fallback. | Selector: 1,199. Executor: 977. Total live Alibaba calls: 2,176. | Not summarized by aggregate report. |
| Large/contextual | one standard task, `large_contextual_payments_failover` | Router selected `pay-ops`, matched fixture, no fallback, baseline and spatial responses succeeded. | Baseline executor: 2,366. Spatial router: 1,619. Spatial executor: 482. Spatial end-to-end: 2,101. | Router: 1595 ms. Baseline executor: 2581 ms. Spatial executor: 2801 ms. |
| Structural 50k | spatial-only smoke already documented | Not rerun in this pass. Existing Alibaba spatial-only note selected `atlas-mesh-s9-final` and completed the reduced-context answer without repair or fallback. | Existing note: spatial total 8,454. | Existing note: 5558 ms total spatial latency. |

## Interpretation

The high-overlap, multi-zone, large/contextual, and structural spatial-only results provide useful evidence that Alibaba can participate in the same benchmark families at small scale with thinking disabled.

The generic effectiveness run is mainly routing and wiring evidence here. It produced valid routing JSON and valid executor outputs, but it was not an effectiveness win under the benchmark's target metric. It also includes deterministic wording-guard corrections, so it should not be overread as a clean quality comparison.

The high-overlap selector result is the cleanest limited routing signal in this pass: `qwen3.6-flash` selected the authoritative `cassini-v31` source in all three runs without fallback.

The multi-zone and large/contextual runs used existing provider protocols with Alibaba-compatible adapters or provider injection. They are useful smoke evidence, but not identical to a dedicated first-class Alibaba CLI benchmark runner.

## Skipped

- Live structural full-context baseline was not run because the user explicitly excluded it for this phase.
- Large repeat campaigns were not run.
- Larger statistical reliability claims were not attempted.

## Limitations

These results are narrow and date-specific. Provider behavior can vary by model version, API settings, quota state, latency, and benchmark prompt details. The results should be used as benchmark replay evidence only, not as production reliability evidence.
