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
- `tasks/05_earth_seasons.md`

## Current task

## 5. Earth seasons, axial tilt, and date or season presets

Add spring equinox, summer solstice, autumn equinox, and winter solstice controls. Use the wording "spring equinox". Do not use "spring solstice".

Implement an Earth axial tilt marker and an explanation of why seasons occur. Earth should move to distinct simplified positions for each preset, with summer solstice visibly different from spring equinox. The Moon should remain visually associated with Earth after season preset changes.
