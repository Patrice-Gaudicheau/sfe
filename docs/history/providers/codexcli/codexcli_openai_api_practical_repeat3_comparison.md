# CodexCLI And OpenAI API Practical Repeat-3 Comparison

This note compares the latest benchmark-local CodexCLI practical repeat-3
`large_contextual` result with the closest existing OpenAI API practical
repeat-3 evidence. It is a documentation comparison only: no benchmark rerun,
API call, or benchmark-code change is required for this note.

## Scope

The comparison supports directional diagnosis, not strict apples-to-apples
provider parity. The CodexCLI run and the closest OpenAI API evidence share the
same practical tier, repeat count, task count, selection mode, and live-call
count, but differ in model versions, router model, output-token budget, and
executor success rates.

Sources:

- `docs/history/providers/codexcli/codexcli_large_contextual_router_inclusive_note.md`
- `docs/openai_paced_equivalent_summary.md`
- `docs/token_cost_metrics.md`

## Benchmark Shape

| Field | CodexCLI reference | Closest OpenAI API evidence |
| --- | --- | --- |
| Executor | `openai-codexcli` | `openai-api` |
| Task tier | `practical` | `practical` |
| Repeat | `3` | `3` |
| Tasks | `3` | `3` |
| Selection mode | `both` | `both` |
| Live calls | `36` | `36` |
| Executor model | `gpt-5.4` | `gpt-5.5` |
| Router model | `gpt-5.4` | `gpt-5.4-nano` |
| Max tokens | `300` | `240` |
| Baseline success | `9/9` | `7/9` |
| Fixture success | `9/9` | `6/9` |
| Router success | `9/9` | `6/9` |
| Router valid selections | `100%` | `9/9` |
| Router matches | `100%` | `9/9` |

## Token Results

| Metric | CodexCLI reference | Closest OpenAI API evidence |
| --- | ---: | ---: |
| Fixture executor input reduction | `40.60%` | about `88%` selected reduction |
| Router executor input reduction | `40.60%` | about `88%` selected reduction |
| Router-inclusive total reduction | `-24.58%` | about `63.40%` |

The OpenAI practical aggregate reports `88.17%` selected reduction and `63.40%`
router-inclusive reduction. The documented token totals for that run are:
baseline `90,526`, fixture `11,244`, router executor `11,315`, router `21,817`,
and router plus executor `33,132`.

## Interpretation

SFE routing quality is not the likely cause of the CodexCLI reduction gap. In
the CodexCLI reference run, router validity and router match rate were both
`100%`, with `9/9` successful router executions and no fallback.

The existing OpenAI API evidence already shows that SFE can produce much
stronger executor-context reductions on the practical tier under the same broad
benchmark shape. The large difference between about `40.60%` CodexCLI executor
input reduction and about `88%` OpenAI API selected reduction is more consistent
with CodexCLI-specific overhead than with an SFE selector failure.

The most plausible causes are CodexCLI prompt wrapping, agentic orchestration
overhead, token accounting differences, or a large fixed context envelope around
each `codex exec --json` call. The user's Codex profile page showing Skills and
Plugins activity, including pipeline-like plugins such as
`$wp_executor_00_pipeline`, `$cdc_parser_00_pipeline`,
`$wp_executor_verifier`, and `$wp_executor_executor`, is a plausible external
clue that additional wrapper or orchestration context may exist. It is not
proof of the token-accounting cause.

## Caveats

This is not strict parity:

- The CodexCLI reference used executor `gpt-5.4`; the OpenAI API practical
  evidence used executor `gpt-5.5`.
- The CodexCLI router used `gpt-5.4`; the OpenAI API router used
  `gpt-5.4-nano`.
- CodexCLI used max tokens `300`; the OpenAI API run used max output tokens
  `240`.
- CodexCLI passed baseline, fixture, and router paths at `9/9`; the OpenAI API
  practical run had Cobalt output omissions and passed baseline `7/9`, fixture
  `6/9`, and router `6/9`.
- The OpenAI API practical evidence is documented as an aggregate summary, not
  as a committed practical-tier raw JSON artifact in `logs/`.

These differences weaken any definitive provider benchmark claim. They do not
weaken the directional diagnosis that CodexCLI's lower apparent reduction is
more likely due to transport, wrapping, orchestration, or accounting overhead
than to SFE routing quality.

## Recommendation

Keep CodexCLI benchmark results documented as provider-specific. The current
OpenAI API practical repeat-3 evidence is sufficient to avoid a full expensive
OpenAI API `gpt-5.4` mirror run right now.

If a small sanity check becomes necessary later, use the smallest possible live
run, for example one practical task, repeat `1`, and max tokens `100`. Do not
run that check unless the cost is explicitly accepted.
