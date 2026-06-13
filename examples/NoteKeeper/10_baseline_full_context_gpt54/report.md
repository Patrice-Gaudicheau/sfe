# Baseline full context gpt-5.4 report

Generated at: `2026-06-13T09:20:56+00:00`

## Scenario

- Workflow: full-context baseline without SFE.
- Provider: `openai-api`.
- Model: `gpt-5.4`.
- Routing: disabled.
- Discovery: disabled.
- Context reduction: disabled.
- Project brief: `../00_project_brief/prompt.md`.
- Task sequence: `../00_project_brief/task_sequence.md`.

## Result

- Success: `true`.
- Total estimated cost: `null`.
- Manual verification: not performed by this runner.

## Task Runs

| Task | Success | Input tokens | Cached input tokens | Output tokens | Latency ms | Error |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `01_initial_scaffold` | `true` | 2820 | 0 | 4489 | 21826 |  |
| `02_persistence_and_crud` | `true` | 6609 | 2304 | 6240 | 26393 |  |
| `03_labels_search_archive` | `true` | 8027 | 2304 | 7689 | 29302 |  |
| `04_checklists_and_pinning` | `true` | 9230 | 2304 | 9477 | 39550 |  |
| `05_responsive_polish` | `true` | 10774 | 2304 | 10291 | 37770 |  |

## Generated Files

- `examples/NoteKeeper/10_baseline_full_context_gpt54/app/index.html`
- `examples/NoteKeeper/10_baseline_full_context_gpt54/app/styles.css`
- `examples/NoteKeeper/10_baseline_full_context_gpt54/app/app.js`
- `examples/NoteKeeper/10_baseline_full_context_gpt54/app/README.md`

## Notes

Task-level prompts, raw responses, parsed file snapshots, and run metadata are stored under `runs/<task>/`.

## Post-run audit

The run artifacts prove a real direct OpenAI API run happened. Each `run.json`
records provider `openai-api`, model `gpt-5.4`, latency, usage metrics, cached
input tokens, `success: true`, and `api_error_retry_count: 0`.

No OpenAI response identifier was captured because the runner saved the model
JSON payload, not the raw provider response envelope.

Token totals:

- `input_tokens`: 37460
- `cached_input_tokens`: 9216
- `output_tokens`: 38186
- `latency_or_wall_clock_duration`: 154841 ms
- `total_estimated_cost`: `null` in `token_usage.json`

Explicit pricing assumptions for the external estimate:

- Non-cached input: $2.50 per 1M tokens
- Cached input: $0.25 per 1M tokens
- Output: $15.00 per 1M tokens

Cost calculation:

- `non_cached_input_tokens = 37460 - 9216 = 28244`
- Input cost: $0.07061000
- Cached input cost: $0.00230400
- Output cost: $0.57279000
- Total estimated cost: $0.64570400

Acceptance summary:

- Project shape: pass
- Core notes workflow: pass
- Persistence: pass
- Labels, search, and archive: pass
- Checklist notes and pinning: partial
- Responsive behavior: not checked visually
- Accessibility and keyboard use: pass by static inspection
- README and reviewability: pass

Defects and caveats:

- Checklist completion is mainly available through the edit/composer form, not directly on note cards.
- Archived notes still show Pin/Unpin actions, which may be confusing.
- Reset behavior may need browser verification.
- Responsive behavior was not fully checked visually.
- The generated app is committed as a raw baseline result, without manual fixes.
