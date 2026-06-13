# SolarSystem3D baseline vs single-model SFE multipass comparison

Compared existing outputs only. The baseline was not rerun. The single-model SFE scenario was run once before this comparison.

## Inputs

| Scenario | Path | Result |
| --- | --- | --- |
| Baseline full context | `examples/SolarSystem3D/10_baseline_full_context_gpt54` | success: `True` across 8/8 tasks |
| SFE single-model multipass | `examples/SolarSystem3D/20_sfe_single_model_gpt54_multipass` | success: `True` across 8/8 tasks |

## Static Sanity

Both outputs contain `index.html`, `styles.css`, `app.js`, and `README.md`. `node --check` passed for the single-model `app/app.js` during this run.

## App Comparison

The generated implementations are different, not byte-equivalent. The single-model SFE result is larger than the baseline in every app file.

| File | Baseline bytes | Single-model bytes | Delta |
| --- | ---: | ---: | ---: |
| `index.html` | 7,159 | 14,402 | +7,243 |
| `styles.css` | 6,879 | 12,393 | +5,514 |
| `app.js` | 48,186 | 65,998 | +17,812 |
| `README.md` | 10,203 | 10,439 | +236 |

Feature markers from static inspection:

| Feature | Baseline marker | Single-model marker |
| --- | --- | --- |
| Three.js static browser app | `true` | `true` |
| Sun, planets, and Moon data | `true` | `true` |
| Procedural textures | `true` | `true` |
| Orbit paths and toggle | `true` | `true` |
| Labels and toggle | `true` | `true` |
| Educational/realistic scale control | `true` | `true` |
| Season presets | `true` | `true` |
| Camera presets | `true` | `true` |
| Selected body information | `true` | `true` |
| Keyboard shortcuts | `true` | `true` |
| Accessibility affordances | `false` | `true` |

Static inspection indicates the single-model output covers the core benchmark surface: Three.js scene setup, all major bodies including the Moon, procedural texture references, orbit/label toggles, scale controls, season presets, camera controls, selected-body information, keyboard support, and accessibility markers. The baseline remains more compact in generated code, while the single-model result appears more expansive and verbose. No manual browser visual verification was performed.

## Transport Diagnostics

| Task | SFE_FILE starts | Canonical ends | Noncanonical closers | Git diffs | Observed transport |
| --- | ---: | ---: | ---: | ---: | --- |
| `01_static_scaffold` | 4 | 4 | 0 | 0 | canonical SFE_FILE blocks |
| `02_data_and_textures` | 3 | 3 | 0 | 0 | canonical SFE_FILE blocks |
| `03_bodies_scale_orbits` | 3 | 3 | 0 | 0 | canonical SFE_FILE blocks |
| `04_animation_time_scale` | 2 | 2 | 0 | 0 | canonical SFE_FILE blocks |
| `05_earth_seasons` | 2 | 2 | 0 | 0 | canonical SFE_FILE blocks |
| `06_camera_labels_focus` | 2 | 2 | 0 | 0 | canonical SFE_FILE blocks |
| `07_info_accessibility` | 2 | 2 | 0 | 0 | canonical SFE_FILE blocks |
| `08_responsive_performance_readme` | 4 | 4 | 0 | 0 | canonical SFE_FILE blocks |

EOF recovery was not needed in this successful rerun: every SFE_FILE block had a canonical `<<<END_SFE_FILE>>>` marker. No recovered file weakens this result.

## Token Comparison

| Scenario | Input | Cached input | Output | Total counted | Delta vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| `10_baseline_full_context_gpt54` | 132,210 | 30,464 | 130,387 | 262,597 | 0.0% |
| `20_sfe_single_model_gpt54_multipass` | 880,149 | 5,376 | 381,053 | 1,261,202 | +380.3% |

The single-model SFE multipass run used 998,605 more counted tokens than the baseline (+380.3%). Input tokens increased by 747,939; output tokens increased by 250,666.

## Model-Role Comparison

| Scenario | Role | Model | Calls | Input | Cached input | Output | Total counted |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | executor | gpt-5.4 | 8 | 132,210 | 30,464 | 130,387 | 262,597 |
| Single-model SFE | discovery | gpt-5.4 | 8 | 9,059 | 0 | 619 | 9,678 |
| Single-model SFE | executor | gpt-5.4 | 24 | 663,270 | 0 | 374,492 | 1,037,762 |
| Single-model SFE | multipass_planner | gpt-5.4 | 8 | 202,728 | 5,376 | 5,549 | 208,277 |
| Single-model SFE | router | gpt-5.4 | 8 | 5,092 | 0 | 393 | 5,485 |

Both scenarios use `gpt-5.4` for all counted model work. Unlike the split benchmark, the single-model run does not shift executor tokens to a smaller model. It exercises SFE context selection and multipass orchestration, but not model-role cost splitting. Counted `gpt-5.4` tokens were 262,597 for baseline versus 1,261,202 for single-model SFE.

## Conclusion

The single-model SFE multipass result is acceptable as a successful benchmark artifact: it completed all eight tasks, produced the required files, passed a JavaScript syntax check, and did not rely on EOF recovery in this rerun. Compared with the baseline, it appears functionally broad but much more token-expensive because all routing, discovery, planning, and execution work used `gpt-5.4`. This suggests SFE context selection without model splitting can complete the benchmark, but the cost advantage is not evident in this run.

## Generated Comparison Files

- `summary.md`
- `cost_table.csv`
- `file_inventory.txt`
- `app_diff_stat.txt`
