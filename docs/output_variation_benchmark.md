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
