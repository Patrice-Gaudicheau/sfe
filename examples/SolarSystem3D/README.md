# SolarSystem3D benchmark

SolarSystem3D is a larger static-web benchmark for evaluating SFE behavior on a constraint-heavy Three.js application. The target app is an educational 3D solar system simulator with procedural textures, all eight planets, Earth's Moon, camera navigation, time controls, season presets, labels, orbit paths, scale modes, and accessibility/performance requirements.

This benchmark is designed to test whether SFE becomes more useful when the prompt and project context are larger than NoteKeeper and contain more cross-cutting constraints. It has not been run yet and does not claim that SFE saves tokens.

## Layout

- `00_project_brief/`: shared product prompt, task sequence, acceptance criteria, and benchmark protocol.
- `10_baseline_full_context_gpt54/`: reserved for a full-context baseline using `gpt-5.4`.
- `20_sfe_single_model_gpt54_multipass/`: reserved for an SFE single-model multipass run using `gpt-5.4`.
- `30_sfe_split_gpt54_router_gpt54mini_executor_multipass/`: reserved for an SFE split-model multipass run using `gpt-5.4` for routing/planning and `gpt-5.4-mini` for execution.
- `90_comparison/`: reserved for result summaries, comparison notes, cost tables, screenshots, and manual review artifacts.

Generated apps should be created inside each scenario's `app/` directory only when that scenario is actually run. No generated app output is included in this skeleton.

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

This directory contains only the benchmark brief and placeholder scenario directories. Do not compare results until the scenarios have been run using the shared brief and task sequence.

