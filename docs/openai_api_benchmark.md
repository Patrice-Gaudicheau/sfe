# OpenAI API Benchmark Path

The `openai-api` backend is the optional direct OpenAI API benchmark path. It
avoids CodexCLI's agentic context overhead and records the router model
explicitly in JSON and Markdown reports.

This OpenAI API benchmark path was used to generate the results summarized in
`docs/openai_validation_report.md`.

Set `SFE_OPENAI_ROUTER_MODEL` and `SFE_OPENAI_EXECUTOR_MODEL` to model ids
available to your OpenAI account before running these commands.

Small-router comparison:

```bash
python runtime/run_effectiveness_benchmark.py \
  --executor openai-api \
  --router openai-api \
  --router-model "$SFE_OPENAI_ROUTER_MODEL" \
  --executor-model "$SFE_OPENAI_EXECUTOR_MODEL" \
  --tasks /tmp/sfe_openai_smoke_tasks.json \
  --repeat 1 \
  --strict \
  --json logs/effectiveness_openai_api_nano_router_smoke.json \
  --md logs/effectiveness_openai_api_nano_router_smoke.md
```

Alternative-router comparison:

```bash
python runtime/run_effectiveness_benchmark.py \
  --executor openai-api \
  --router openai-api \
  --router-model "$SFE_OPENAI_ROUTER_MODEL" \
  --executor-model "$SFE_OPENAI_EXECUTOR_MODEL" \
  --tasks /tmp/sfe_openai_smoke_tasks.json \
  --repeat 1 \
  --strict \
  --json logs/effectiveness_openai_api_mini_router_smoke.json \
  --md logs/effectiveness_openai_api_mini_router_smoke.md
```

Both commands require `OPENAI_API_KEY` in the environment or in a local `.env`
file copied from `.env.example`.
