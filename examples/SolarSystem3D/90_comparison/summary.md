# SolarSystem3D benchmark comparison

Compared existing outputs only. No baseline or split scenario was rerun.

## Inputs

| Scenario | Path | Result |
| --- | --- | --- |
| Baseline full context | `examples/SolarSystem3D/10_baseline_full_context_gpt54` | success: `True` across 8 tasks |
| SFE split multipass | `examples/SolarSystem3D/30_sfe_split_gpt54_router_gpt54mini_executor_multipass` | success: `True` across 8 tasks |

## App comparison

Both outputs produced the expected static app files: `index.html`, `styles.css`, `app.js`, and `README.md`. The generated implementations are different, not byte-equivalent.

The split result is smaller: `app.js` is 25,454 bytes versus 48,186 bytes in the baseline; `styles.css` is 3,148 bytes versus 6,879 bytes; `index.html` is 5,171 bytes versus 7,159 bytes; `README.md` is 2,280 bytes versus 10,203 bytes.

Feature markers found in the split result:

| Feature | Present |
| --- | --- |
| Three.js static browser app | `true` |
| Sun, planets, and Moon data | `true` |
| Procedural textures | `true` |
| Orbit paths and toggle | `true` |
| Labels and toggle | `true` |
| Educational/realistic scale control | `true` |
| Season presets | `true` |
| Camera presets | `true` |
| Selected body information | `true` |
| Keyboard shortcuts | `true` |

The baseline appears more elaborate in UI documentation and implementation detail. It includes a richer README, a larger JavaScript implementation, a date input, more explicit selected-body panel defaults, overlay chips, and additional keyboard details such as bracket speed adjustment and arrow-key day stepping. The split result still covers the core benchmark surface: procedural Three.js solar system, all required bodies, Saturn rings by code marker, orbit and label toggles, simplified season presets, scale mode, camera presets, click selection, and keyboard shortcuts.

No manual browser visual verification was performed by this comparison. Based on static file inspection, the split app looks acceptable as a benchmark result relative to the baseline, but likely less polished and less feature-rich in explanatory UI and documentation.

## Token comparison

| Scenario | Input | Cached input | Output | Total | Delta vs baseline |
| --- | ---: | ---: | ---: | ---: | ---: |
| `10_baseline_full_context_gpt54` | 132,210 | 30,464 | 130,387 | 262,597 | 0.0% |
| `30_sfe_split_gpt54_router_gpt54mini_executor_multipass` | 121,578 | 0 | 51,585 | 173,163 | -34.1% |

The split run used 89,434 fewer total tokens than the baseline (-34.1%). Input tokens decreased by 10,632 (-8.0%); output tokens decreased by 78,802 (-60.4%).

## Model-role comparison

| Role | Model | Calls | Input | Output | Total |
| --- | --- | ---: | ---: | ---: | ---: |
| discovery | gpt-5.4 | 8 | 9,122 | 616 | 9,738 |
| executor | gpt-5.4-mini | 8 | 101,665 | 50,039 | 151,704 |
| multipass_planner | gpt-5.4 | 1 | 5,635 | 604 | 6,239 |
| router | gpt-5.4 | 8 | 5,156 | 326 | 5,482 |

Baseline used all 262,597 counted tokens on `gpt-5.4`. The split run used 21,459 counted tokens on `gpt-5.4` router/discovery/planning roles and 151,704 counted tokens on `gpt-5.4-mini` executor work. That is 241,138 fewer expensive-model tokens than baseline (-91.8%).

This is the strongest cost implication from this comparison: the split architecture both reduced total counted tokens and shifted most execution tokens to `gpt-5.4-mini`. Actual dollar cost is not computed because both source reports have `total_estimated_cost: null`.

## Generated comparison files

- `summary.md`
- `cost_table.csv`
- `file_inventory.txt`
- `app_diff_stat.txt`

## Conclusion

The SFE split router/executor multipass result is acceptable compared to the baseline for benchmark purposes. It completed all eight tasks, produced the expected static app files, retained the main functional requirements, used fewer total tokens, and greatly reduced `gpt-5.4` token exposure. The tradeoff is that the baseline output appears more detailed and polished, especially in documentation, accessibility affordances, and finer-grained controls.
