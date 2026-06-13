# SolarSystem3D benchmark

SolarSystem3D is a larger static-web benchmark for evaluating SFE behavior on a constraint-heavy Three.js application. The target app is an educational 3D solar system simulator with procedural textures, all eight planets, Earth's Moon, camera navigation, time controls, season presets, labels, orbit paths, scale modes, and accessibility/performance requirements.

This benchmark is designed to test whether SFE becomes more useful when the prompt and project context are larger than NoteKeeper and contain more cross-cutting constraints. The current artifacts are benchmark evidence, not a claim that SFE saves tokens.

## Layout

- `00_project_brief/`: shared product prompt, task sequence, acceptance criteria, and benchmark protocol.
- `10_baseline_full_context_gpt54/`: full-context baseline using `gpt-5.4`.
- `20_sfe_single_model_gpt54_multipass/`: SFE single-model multipass run using `gpt-5.4`.
- `30_sfe_split_gpt54_router_gpt54mini_executor_multipass/`: SFE split-model multipass run using `gpt-5.4` for routing/planning and `gpt-5.4-mini` for execution.
- `90_comparison/`: result summaries and comparison notes.

Generated apps are stored inside each scenario's `app/` directory. Task-level run evidence is stored under each scenario's `runs/` directory.

## Target Generated App Shape

Each scenario should produce a static app with this shape:

```text
app/
  index.html
  styles.css
  app.js
  README.md
```

If a runner chooses to vendor Three.js instead of using pinned CDN URLs, it may add a documented `app/vendor/` directory. The app must not require a backend, database, package manager, bundler, transpiler, or generated audio pipeline.

## Texture Approach

The benchmark requires visible planet-like textures, but they should be generated procedurally inside the app with Canvas APIs. This avoids copyrighted planet texture assets, fragile external image downloads, and repository licensing uncertainty.

Three.js itself may be loaded through pinned browser URLs or vendored locally by a scenario runner. Any external library choice must be documented in the generated app README and in the scenario report.

## Current Status

Current committed artifacts preserve the first benchmark runs:

| Scenario | Result | Notes |
| --- | --- | --- |
| `10_baseline_full_context_gpt54` | Success | Completed all 8 tasks. The generated app appears manually testable, and `node --check app/app.js` passed during validation. Token usage was 132,210 input tokens, 30,464 cached input tokens, and 130,387 output tokens. |
| `20_sfe_single_model_gpt54_multipass` | Failed | The clean run completed tasks 1-2 and failed at `03_bodies_scale_orbits` with `hunk_preimage_mismatch` on `app/app.js`. A later no-clean continuation attempt restarted at task 1 and also failed with a patch preimage mismatch; those top-level report artifacts are preserved as generated evidence. |
| `30_sfe_split_gpt54_router_gpt54mini_executor_multipass` | Failed | Completed tasks 1-2 and failed at `03_bodies_scale_orbits` with `hunk_location_mismatch` on `app/app.js`. The partial app passed `node --check app/app.js` during validation. |

The current SFE runner evidence is negative or inconclusive for SolarSystem3D. Both SFE scenarios failed on patch application against a large `app/app.js`, not on truncated JSON. The next planned experiment is a manual `sfe-tui` run against an existing target directory to test continuation behavior outside the benchmark runner restart flow.
