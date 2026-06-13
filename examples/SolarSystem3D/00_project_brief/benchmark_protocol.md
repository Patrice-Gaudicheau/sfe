# SolarSystem3D benchmark protocol

This benchmark uses the same project brief, acceptance criteria, and task sequence across three development scenarios. The goal is to compare full-context generation with SFE-driven workflows on a larger static web application than NoteKeeper.

Do not change `00_project_brief/prompt.md`, `00_project_brief/acceptance_criteria.md`, or `00_project_brief/task_sequence.md` between scenarios. Do not create generated app files until a scenario is actually run.

## Hypothesis under test

SolarSystem3D is designed to test whether SFE becomes more useful when the prompt and project context are larger, more interdependent, and more constraint-heavy than a compact CRUD-style app. The benchmark must not be interpreted as proof of token savings before scenario results are collected.

The workload is larger than NoteKeeper because it combines:

- 3D rendering setup and browser runtime constraints.
- Procedural texture generation.
- Astronomy data and simplification rules.
- Animation and camera state.
- Multiple UI control groups.
- Responsive layout constraints.
- Accessibility and keyboard requirements.
- Performance constraints around render loops, geometry, textures, and event listeners.
- Documentation requirements for static execution and astronomy simplifications.

## Scenarios

1. `10_baseline_full_context_gpt54`: baseline full-context run with `gpt-5.4` only, without SFE.
2. `20_sfe_single_model_gpt54_multipass`: SFE single-model run with `gpt-5.4` used for routing, discovery, planning, review, and execution, with multipass enabled.
3. `30_sfe_split_gpt54_router_gpt54mini_executor_multipass`: SFE split-model run with `gpt-5.4` for routing, discovery, planning, and review, `gpt-5.4-mini` for execution, with multipass enabled.

Use the same eight tasks for every scenario. A scenario should only advance to the next task after recording the current task output and any validation notes available for that workflow.

## Scenario output structure

Each scenario folder may contain:

```text
app/
  index.html
  styles.css
  app.js
  README.md
runs/
  01_static_scaffold/
  02_data_and_textures/
  03_bodies_scale_orbits/
  04_animation_time_scale/
  05_earth_seasons/
  06_camera_labels_focus/
  07_info_accessibility/
  08_responsive_performance_readme/
report.md
token_usage.json
```

The exact run artifact names may vary by runner, but reports should preserve enough task-level detail for comparison.

## Run capture requirements

After each scenario run, capture the following information when available:

- Provider and model per role, including router, discovery, planner, executor, reviewer, or equivalent roles.
- Input tokens.
- Cached input tokens.
- Output tokens.
- Total tokens.
- Total estimated cost.
- Latency or wall-clock duration.
- Number of provider calls by role.
- Selected context size for SFE calls when available.
- Whether multipass was used and how many passes were required.
- Success or failure for each task.
- Generated or modified files.
- Static execution method used: direct file open, simple static server, or both.
- Manual verification notes.
- Known defects and deviations from the acceptance criteria.

If a metric is unavailable, record it as `null` in `token_usage.json` and explain the gap in `report.md`. Do not invent token, cost, latency, or pass-count values.

## Validation guidance

Automated validation for this benchmark is expected to be limited because the target is an interactive 3D app. Use a combination of file review, static checks, and manual browser testing.

Minimum review checks:

- Confirm only expected app files and optional documented vendor files were created.
- Confirm no external texture images are referenced.
- Confirm no audio assets or audio APIs are used.
- Confirm all required body names appear in app code or data.
- Confirm "spring equinox" appears and "spring solstice" does not appear.
- Confirm run instructions exist in `app/README.md`.
- Confirm the app can be loaded by the documented method.
- Manually inspect the scene and controls against the acceptance criteria.

If Playwright or browser screenshots are used in a future run, store them under the scenario `runs/` directories or `90_comparison/screenshots/`.

## Comparison methodology

Compare scenarios on both strict and practical outcomes.

Strict outcome:

- The scenario completes all eight tasks.
- The final app meets all acceptance criteria.
- No unapproved files, backend services, build steps, or generated app outputs outside the scenario directory are introduced.

Practical outcome:

- The final app is usable for the core educational workflow even if minor nonblocking criteria are missed.
- Major omissions, such as missing planets, missing procedural textures, broken controls, no season presets, or no working 3D scene, should not be treated as practical success.

Use the same manual verification checklist for every scenario. When comparing failed or partial runs, compare only the largest common completed task window unless a separate "available total" table is clearly labeled.

## Token and cost interpretation guidelines

Do not claim that SFE saves tokens from this benchmark until the collected data supports that claim.

Report at least these views:

- Total token volume by scenario.
- Input, cached input, and output tokens by scenario.
- Expensive-model token exposure by scenario.
- Smaller-executor token exposure by scenario.
- Estimated dollar cost by scenario when pricing is known.
- Comparable-scope totals for scenarios that fail before completing all tasks.
- Available-run totals that include failed attempts, clearly labeled as such.

Interpret split-model results carefully. A split-model SFE run can reduce expensive-model exposure or estimated dollar cost while increasing total token volume. Those are different claims and should not be merged.

Interpret multipass results carefully. Multipass may improve reliability, may increase tokens, or may do both. Treat reliability, total token volume, expensive-model exposure, and dollar cost as separate measurements.

## Comparison artifacts

After all scenarios have been run, populate `90_comparison/README.md` or additional files under `90_comparison/` with:

- Scenario outcome table.
- Acceptance criteria pass/fail notes.
- Token and cost tables.
- Static execution notes.
- Screenshots or manual review notes.
- Final interpretation and caveats.

