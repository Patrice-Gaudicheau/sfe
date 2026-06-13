# SolarSystem3D SFE single-model multipass benchmark task

Use the SFE-selected workspace context. The controlled workspace contains only the benchmark brief under `brief/`, task metadata under `tasks/`, and the current generated app under `app/`.

This scenario uses one OpenAI model for router, discovery, multipass planning, and patch generation. Multipass is intentionally forced on.

You are implementing the SolarSystem3D static Three.js browser app. Edit only these workspace files:

- `app/index.html`
- `app/styles.css`
- `app/app.js`
- `app/README.md`

Do not create package files, server code, backend code, screenshots, logs, or files outside `app/`. Do not add external texture images or audio. A pinned browser Three.js CDN import is allowed, and a documented simple static-server fallback is allowed if browser module restrictions require it.

Consult these benchmark documents from selected context when available:

- `brief/prompt.md`
- `brief/acceptance_criteria.md`
- `brief/task_sequence.md`
- `tasks/07_info_accessibility.md`

## Current task

## 7. Info panel, toggles, keyboard support, and accessibility pass

Complete the selected-body info panel with name, type, approximate distance, orbital period, rotation period, and description. Add orbit visibility and label visibility toggles if not already complete. Add practical keyboard shortcuts or keyboard-operable controls for core actions, visible focus states, accessible control names, and touch-friendly sizing where practical.
