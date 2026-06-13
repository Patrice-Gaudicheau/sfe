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
- `tasks/01_static_scaffold.md`

## Current task

## 1. Static scaffold and Three.js scene shell

Create the initial static app files under the scenario's `app/` directory: `index.html`, `styles.css`, `app.js`, and `README.md`. Establish the SolarSystem3D app shell, full-screen 3D canvas, primary control areas, selected-body panel placeholder, responsive layout, and baseline Three.js scene with camera, renderer, lighting, resize handling, and a procedural star background.

Document whether the app opens directly from `index.html` or requires a simple static server because of browser module loading rules.
